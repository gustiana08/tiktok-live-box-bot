"""TikTok Live lucky box (kotak harta karun) detector.

Connects to individual TikTok Live streams via the TikTokLive library
and listens for treasure box / envelope events.

Multiple detection strategies:
1. EnvelopeEvent — official protobuf event for treasure boxes
2. EnvelopePortalEvent — portal/popup notification for treasure boxes
3. GoodyBagEvent / CapsuleEvent — alternative reward events
4. GiftEvent — filter gifts related to treasure/lucky box
5. Raw event scanning — fallback byte-pattern matching
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
            logger.info("Starting detector for @%s ...", self.username)
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
                "Connected to @%s (Room:%s Region:%s Viewers:%s)",
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

        self._register_envelope_events()
        self._register_gift_events()
        self._register_raw_scanner()

    def _register_envelope_events(self) -> None:
        """Register envelope/treasure box event listeners."""
        if not self._client:
            return

        # 1. EnvelopeEvent — primary treasure box event
        try:
            from TikTokLive.events import EnvelopeEvent

            @self._client.on(EnvelopeEvent)
            async def on_envelope(event: EnvelopeEvent) -> None:
                logger.info("🎁 ENVELOPE EVENT in @%s!", self.username)
                box_info = self._parse_envelope_event(event)
                box_info["stream_info"] = self._stream_info
                if self.on_box_detected:
                    await self.on_box_detected(self.username, self._room_id, box_info)

        except ImportError:
            logger.debug("EnvelopeEvent not available.")

        # 2. EnvelopePortalEvent — treasure box portal/popup
        try:
            from TikTokLive.events import EnvelopePortalEvent

            @self._client.on(EnvelopePortalEvent)
            async def on_portal(event: EnvelopePortalEvent) -> None:
                logger.info("🎁 ENVELOPE PORTAL in @%s!", self.username)
                box_info = {
                    "type": "envelope_portal",
                    "stream_info": self._stream_info,
                }
                if self.on_box_detected:
                    await self.on_box_detected(self.username, self._room_id, box_info)

        except ImportError:
            logger.debug("EnvelopePortalEvent not available.")

        # 3. GoodyBagEvent — alternative reward mechanism
        try:
            from TikTokLive.events import GoodyBagEvent

            @self._client.on(GoodyBagEvent)
            async def on_goody(event: GoodyBagEvent) -> None:
                logger.info("🎁 GOODY BAG in @%s!", self.username)
                box_info = {
                    "type": "goody_bag",
                    "stream_info": self._stream_info,
                }
                if self.on_box_detected:
                    await self.on_box_detected(self.username, self._room_id, box_info)

        except ImportError:
            logger.debug("GoodyBagEvent not available.")

        # 4. CapsuleEvent — capsule reward
        try:
            from TikTokLive.events import CapsuleEvent

            @self._client.on(CapsuleEvent)
            async def on_capsule(event: CapsuleEvent) -> None:
                logger.info("🎁 CAPSULE EVENT in @%s!", self.username)
                box_info = {
                    "type": "capsule",
                    "stream_info": self._stream_info,
                }
                if self.on_box_detected:
                    await self.on_box_detected(self.username, self._room_id, box_info)

        except ImportError:
            logger.debug("CapsuleEvent not available.")

    def _register_gift_events(self) -> None:
        """Register gift event listener to detect treasure-box-related gifts."""
        if not self._client:
            return

        try:
            from TikTokLive.events import GiftEvent

            @self._client.on(GiftEvent)
            async def on_gift(event: GiftEvent) -> None:
                gift_name = ""
                gift_id = 0

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

                box_keywords = [
                    "treasure",
                    "lucky",
                    "chest",
                    "kotak",
                    "keberuntungan",
                    "harta",
                    "karun",
                    "envelope",
                    "mystery",
                    "box",
                ]
                name_lower = gift_name.lower()
                if any(kw in name_lower for kw in box_keywords):
                    logger.info(
                        "🎁 BOX GIFT in @%s: %s (ID:%s)",
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
            logger.debug("GiftEvent not available.")

    def _register_raw_scanner(self) -> None:
        """Scan raw/unknown events for treasure box byte patterns."""
        if not self._client:
            return

        try:
            from TikTokLive.events import UnknownEvent

            @self._client.on(UnknownEvent)
            async def on_unknown(event: UnknownEvent) -> None:
                raw = event.bytes if hasattr(event, "bytes") and event.bytes else b""
                if not raw:
                    return

                markers = [
                    b"envelope",
                    b"Envelope",
                    b"treasure",
                    b"Treasure",
                    b"lucky_box",
                    b"TreasureBox",
                    b"RedEnvelop",
                ]
                if any(marker in raw for marker in markers):
                    logger.info(
                        "🎁 RAW ENVELOPE in @%s (bytes:%d)",
                        self.username,
                        len(raw),
                    )
                    box_info = {
                        "type": "raw_envelope",
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
        """Extract useful info from an EnvelopeEvent (WebcastEnvelopeMessage).

        Proto fields (MessageRedEnvelopInfo):
          - envelope_id, business_type, envelope_idc
          - send_user_name, send_user_id, send_user_avatar
          - diamond_count, people_count, unpack_at
          - create_time, skin_id
        """
        info: dict[str, Any] = {"type": "envelope"}

        env = getattr(event, "envelope_info", None)
        if env is not None:
            info["diamond_count"] = getattr(env, "diamond_count", 0)
            info["people_count"] = getattr(env, "people_count", 0)
            info["send_user_name"] = getattr(env, "send_user_name", "")
            info["send_user_id"] = getattr(env, "send_user_id", "")
            info["envelope_id"] = getattr(env, "envelope_id", "")
            info["create_time"] = getattr(env, "create_time", "")
        else:
            for attr in [
                "coins",
                "diamond_count",
                "diamonds",
                "description",
                "title",
            ]:
                val = getattr(event, attr, None)
                if val is not None:
                    info[attr] = val

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
                    break
                except Exception as e:
                    retry_count += 1
                    wait_time = min(30 * retry_count, 120)
                    logger.warning(
                        "Detector @%s failed (%d/%d): %s. Retry in %ds.",
                        username,
                        retry_count,
                        max_retries,
                        e,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)
            else:
                logger.error("Detector @%s exceeded max retries. Removing.", username)

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
