"""Main entry point for the TikTok Live Lucky Box Telegram Bot."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from bot.config import settings
from bot.detector import MultiStreamDetector
from bot.discovery import LiveDiscovery
from bot.telegram_notifier import notify_bot_status, notify_lucky_box

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Reduce noise from httpx and other libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def on_box_detected(username: str, room_id: int | str, box_info: dict[str, Any]) -> None:
    """Callback when a lucky box is detected."""
    logger.info("LUCKY BOX! @%s Room:%s", username, room_id)
    await notify_lucky_box(username=username, room_id=room_id, box_info=box_info)


async def on_stream_connected(username: str, room_id: int | str, stream_info: dict[str, Any]) -> None:
    """Log when connected to a live stream (no Telegram notification)."""
    logger.info("LIVE connected: @%s Room:%s", username, room_id)


class Bot:
    """Main bot orchestrator."""

    def __init__(self) -> None:
        self.discovery = LiveDiscovery()
        self.multi_detector = MultiStreamDetector(
            on_box_detected=on_box_detected,
            on_stream_connected=on_stream_connected,
            max_concurrent=settings.max_concurrent_streams,
        )
        self._running = False
        self._scan_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the bot."""
        self._running = True
        setup_logging()

        logger.info("=" * 60)
        logger.info("TikTok Live Lucky Box Telegram Bot")
        logger.info("=" * 60)

        # Validate configuration
        if not settings.telegram_bot_token:
            logger.error("TELEGRAM_BOT_TOKEN is not set! Notifications will not work.")
        if not settings.telegram_chat_id:
            logger.error("TELEGRAM_CHAT_ID is not set! Notifications will not work.")

        # Send startup notification
        await notify_bot_status(
            "start",
            detail=(
                f"Scan interval: {settings.scan_interval}s\n"
                f"Max concurrent streams: {settings.max_concurrent_streams}\n"
                f"Manual usernames: {len(settings.username_list)}"
            ),
        )

        # Start the scan loop
        self._scan_task = asyncio.create_task(self._scan_loop())

        # Wait for shutdown
        try:
            await self._wait_for_shutdown()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the bot gracefully."""
        if not self._running:
            return
        self._running = False

        logger.info("Shutting down...")

        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

        await self.multi_detector.stop_all()
        await notify_bot_status("stop", detail="Bot stopped gracefully.")
        logger.info("Bot stopped.")

    async def _scan_loop(self) -> None:
        """Periodically scan for new live streams and monitor them."""
        while self._running:
            try:
                await self._scan_once()
            except Exception:
                logger.error("Error during scan cycle.", exc_info=True)

            await asyncio.sleep(settings.scan_interval)

    async def _scan_once(self) -> None:
        """Perform a single scan cycle."""
        new_streams: list[str] = []

        # Check manually configured usernames
        if settings.username_list:
            manual_lives = await self.discovery.check_multiple_users(settings.username_list)
            for stream in manual_lives:
                if stream.username not in self.multi_detector.monitored_usernames:
                    new_streams.append(stream.username)

        # Discover trending lives
        trending = await self.discovery.discover_trending_lives()
        for stream in trending:
            if stream.username not in self.multi_detector.monitored_usernames:
                new_streams.append(stream.username)

        # Add new streams to detector (with delay to avoid rate limits)
        added = 0
        for username in new_streams:
            if self.multi_detector.active_count >= settings.max_concurrent_streams:
                logger.info(
                    "Max concurrent streams reached (%d). Skipping.",
                    settings.max_concurrent_streams,
                )
                break
            success = await self.multi_detector.add_stream(username)
            if success:
                added += 1
                # Rate limit: wait between connections
                await asyncio.sleep(3)

        if added > 0:
            logger.info(
                "Added %d new streams. Total monitoring: %d",
                added,
                self.multi_detector.active_count,
            )

    async def _wait_for_shutdown(self) -> None:
        """Wait for a shutdown signal."""
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def signal_handler() -> None:
            logger.info("Shutdown signal received.")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, signal_handler)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        await stop_event.wait()


def main() -> None:
    """Entry point."""
    bot = Bot()
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")


if __name__ == "__main__":
    main()
