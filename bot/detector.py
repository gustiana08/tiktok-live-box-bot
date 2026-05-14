"""TikTok Live lucky box (kotak keberuntungan) detector.

Connects to individual TikTok Live streams via the TikTokLive library
and listens for treasure box / envelope events.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent

logger = logging.getLogger(__name__)

# Callback types
BoxCallback = Callable[[str, int | str, dict[str, Any]], Coroutine[Any, Any, None]]
ConnectCallback = Callable[[str, int | str, dict[str, Any]], Coroutine[Any, Any, None]]


class LuckyBoxDetector:
    """Monitors a single TikTok Live stream for lucky box events."""

    def __init__(
        self,
        username: str,
        on_box_detected: BoxCallback | None = None,
        on_stream_connected: ConnectCallback | None = None,
    ) -> None:
        self.username = username.lstrip("@")
        self.on_box_detected = on_box_detected
        self.on_stream_connected = on_stream_connected
        self._client: TikTokLiveClient | None = None
        self._running = False
        self._room_id: int | str = 0
        self._stream_info: dict[str, Any] = {}

    async def start(self) -> None:
        """Start monitoring the stream for lucky boxes."""
        # Reset state for fresh start / retry
        self._running = False
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass

        self._client = TikTokLiveClient(unique_id=f"@{self.username}")
        self._setup_event_handlers()
        self._running = True

        try:
            logger.info("Starting lucky box detector for @%s ...", self.username)
            await self._client.start(fetch_room_info=True)
        except Exception as e:
            self._running = False
            logger.error("Failed to start detector for @%s: %s", self.username, e)
            raise
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
        logger.info("Detector for @%s stopped.", self.username)

    @property
    def is_running(self) -> bool:
        return self._running

    def _setup_event_handlers(self) -> None:
        """Register event handlers on the TikTokLive client."""
        if not self._client:
            return

        @self._client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent) -> None:
            self._room_id = self._client.room_id if self._client else 0
            self._stream_info = self._extract_stream_info()
            logger.info(
                "Connected to @%s (Room ID: %s, Region: %s, Viewers: %s)",
                event.unique_id,
                self._room_id,
                self._stream_info.get("region", "?"),
                self._stream_info.get("viewer_count", "?"),
            )
            if self.on_stream_connected:
                await self.on_stream_connected(self.username, self._room_id, self._stream_info)

        @self._client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent) -> None:
            self._running = False
            logger.info("Disconnected from @%s", self.username)

        # Listen for ALL events and filter for lucky box related ones.
        # The treasure box / lucky box in TikTok uses WebcastEnvelopeMessage
        # which maps to EnvelopeEvent in TikTokLive library.
        try:
            from TikTokLive.events import EnvelopeEvent

            @self._client.on(EnvelopeEvent)
            async def on_envelope(event: EnvelopeEvent) -> None:
                logger.info("EnvelopeEvent (treasure box) detected in @%s!", self.username)
                box_info = self._parse_envelope_event(event)
                box_info["stream_info"] = self._stream_info
                if self.on_box_detected:
                    await self.on_box_detected(self.username, self._room_id, box_info)
        except ImportError:
            logger.warning(
                "EnvelopeEvent not available in this TikTokLive version. Falling back to raw event scanning."
            )

        # Also listen for gift events that might be related to lucky boxes
        try:
            from TikTokLive.events import GiftEvent

            @self._client.on(GiftEvent)
            async def on_gift(event: GiftEvent) -> None:
                gift_name = ""
                gift_id = 0

                # Try to extract gift info from the event
                try:
                    if hasattr(event, "gift"):
                        gift_obj = event.gift
                        if hasattr(gift_obj, "name"):
                            gift_name = gift_obj.name
                        elif hasattr(gift_obj, "describe"):
                            gift_name = gift_obj.describe
                        if hasattr(gift_obj, "id"):
                            gift_id = gift_obj.id
                    elif hasattr(event, "name"):
                        gift_name = event.name
                except Exception:
                    pass

                # Check if this gift is a lucky box / treasure box
                box_keywords = [
                    "treasure",
                    "lucky",
                    "box",
                    "chest",
                    "kotak",
                    "keberuntungan",
                    "envelope",
                    "mystery",
                ]
                name_lower = gift_name.lower()
                if any(kw in name_lower for kw in box_keywords):
                    logger.info(
                        "Lucky box gift detected in @%s: %s (ID: %s)",
                        self.username,
                        gift_name,
                        gift_id,
                    )
                    box_info = {
                        "type": "gift_box",
                        "gift_name": gift_name,
                        "gift_id": gift_id,
                        "stream_info": self._stream_info,
                    }
                    if self.on_box_detected:
                        await self.on_box_detected(self.username, self._room_id, box_info)
        except ImportError:
            logger.warning("GiftEvent not available.")

        # Catch-all for unknown/raw events that might contain envelope data
        try:
            from TikTokLive.events import UnknownEvent

            @self._client.on(UnknownEvent)
            async def on_unknown(event: UnknownEvent) -> None:
                # Check raw bytes for envelope/treasure box signatures
                raw = event.bytes if hasattr(event, "bytes") and event.bytes else b""
                if not raw:
                    return

                # Look for protobuf patterns related to envelope/treasure box
                envelope_markers = [b"envelope", b"treasure", b"lucky_box", b"Envelope"]
                if any(marker in raw for marker in envelope_markers):
                    logger.info("Possible lucky box detected via raw event in @%s", self.username)
                    box_info = {
                        "type": "raw_envelope",
                        "description": "Detected via raw event data",
                        "size": len(raw),
                        "stream_info": self._stream_info,
                    }
                    if self.on_box_detected:
                        await self.on_box_detected(self.username, self._room_id, box_info)
        except ImportError:
            pass

    def _extract_stream_info(self) -> dict[str, Any]:
        """Extract account/stream info from the connected TikTokLive client."""
        info: dict[str, Any] = {"username": self.username}
        if not self._client or not self._client.room_info:
            return info

        room = self._client.room_info
        owner = room.get("owner", {})

        info["nickname"] = owner.get("nickname", "")
        info["title"] = room.get("title", "")
        info["viewer_count"] = room.get("user_count", 0)
        info["share_url"] = room.get("share_url", "")

        # Region: try multiple fields, fallback to language from share_url
        region = (
            room.get("idc_region", "") or owner.get("region", "") or room.get("region", "") or owner.get("country", "")
        )
        if not region:
            share_url = room.get("share_url", "")
            if "language=" in share_url:
                region = share_url.split("language=")[-1].split("&")[0].upper()
        info["region"] = region

        follow_info = owner.get("follow_info", {})
        if isinstance(follow_info, dict):
            info["follower_count"] = follow_info.get("follower_count", 0)

        info["bio"] = owner.get("bio_description", "")
        info["display_id"] = owner.get("display_id", "")

        return info

    def _parse_envelope_event(self, event: Any) -> dict[str, Any]:
        """Extract useful information from an EnvelopeEvent."""
        info: dict[str, Any] = {"type": "envelope"}

        # Try to extract common fields from the envelope event
        for attr in ["coins", "diamond_count", "diamonds", "description", "title"]:
            if hasattr(event, attr):
                info[attr] = getattr(event, attr)

        # Try nested structures
        if hasattr(event, "envelope_info"):
            env_info = event.envelope_info
            for attr in ["coins", "diamond_count"]:
                if hasattr(env_info, attr):
                    info[attr] = getattr(env_info, attr)

        return info


class MultiStreamDetector:
    """Manages multiple LuckyBoxDetector instances concurrently."""

    def __init__(
        self,
        on_box_detected: BoxCallback | None = None,
        on_stream_connected: ConnectCallback | None = None,
        max_concurrent: int = 10,
    ) -> None:
        self.on_box_detected = on_box_detected
        self.on_stream_connected = on_stream_connected
        self.max_concurrent = max_concurrent
        self._detectors: dict[str, LuckyBoxDetector] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def add_stream(self, username: str) -> bool:
        """Add a stream to monitor. Returns True if successfully added."""
        username = username.lstrip("@")
        if username in self._detectors:
            logger.debug("@%s is already being monitored.", username)
            return False

        detector = LuckyBoxDetector(
            username=username,
            on_box_detected=self.on_box_detected,
            on_stream_connected=self.on_stream_connected,
        )
        self._detectors[username] = detector

        task = asyncio.create_task(self._run_detector(username, detector))
        self._tasks[username] = task
        return True

    async def remove_stream(self, username: str) -> None:
        """Stop monitoring a stream."""
        username = username.lstrip("@")
        if username in self._detectors:
            await self._detectors[username].stop()
            del self._detectors[username]
        if username in self._tasks:
            self._tasks[username].cancel()
            del self._tasks[username]

    async def _run_detector(self, username: str, detector: LuckyBoxDetector) -> None:
        """Run a single detector with semaphore control and auto-restart."""
        async with self._semaphore:
            retry_count = 0
            max_retries = 3
            while retry_count < max_retries:
                try:
                    await detector.start()
                    # start() returned normally (stream ended) — reset retries
                    break
                except Exception as e:
                    retry_count += 1
                    wait_time = min(30 * retry_count, 120)
                    logger.warning(
                        "Detector for @%s failed (attempt %d/%d): %s. Retrying in %ds...",
                        username,
                        retry_count,
                        max_retries,
                        e,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)
            else:
                logger.error("Detector for @%s exceeded max retries. Removing.", username)

            self._detectors.pop(username, None)

    async def stop_all(self) -> None:
        """Stop all detectors."""
        for username in list(self._detectors.keys()):
            await self.remove_stream(username)

    @property
    def active_count(self) -> int:
        return sum(1 for d in self._detectors.values() if d.is_running)

    @property
    def monitored_usernames(self) -> list[str]:
        return list(self._detectors.keys())
