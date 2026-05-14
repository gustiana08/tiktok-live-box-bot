"""TikTok Live stream discovery module.

Discovers currently active TikTok Live streams via web scraping.
Since TikTok has no public API for listing live streams, this module
uses multiple strategies to find active streams.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TIKTOK_BASE = "https://www.tiktok.com"

# Common headers to mimic a real browser
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.tiktok.com/",
}


@dataclass
class LiveStreamInfo:
    """Represents a discovered TikTok Live stream."""

    username: str
    room_id: str = ""
    title: str = ""
    viewer_count: int = 0
    source: str = "manual"

    @property
    def live_url(self) -> str:
        return f"{TIKTOK_BASE}/@{self.username}/live"


@dataclass
class LiveDiscovery:
    """Discovers active TikTok Live streams through multiple strategies."""

    _known_streams: dict[str, LiveStreamInfo] = field(default_factory=dict)

    async def check_user_is_live(self, username: str) -> LiveStreamInfo | None:
        """Check if a specific user is currently live."""
        username = username.lstrip("@")
        url = f"{TIKTOK_BASE}/@{username}/live"

        try:
            async with httpx.AsyncClient(
                headers=BROWSER_HEADERS,
                follow_redirects=True,
                timeout=15,
            ) as client:
                resp = await client.get(url)

                if resp.status_code != 200:
                    return None

                html = resp.text

                # Look for room_id in the page source
                room_match = re.search(r'"roomId"\s*:\s*"(\d+)"', html)
                if not room_match:
                    room_match = re.search(r"room_id[=:](\d+)", html)

                if not room_match:
                    logger.debug("@%s is not live or room ID not found.", username)
                    return None

                room_id = room_match.group(1)

                # Extract title
                title = ""
                title_match = re.search(r'"title"\s*:\s*"([^"]*)"', html)
                if title_match:
                    title = title_match.group(1)

                # Extract viewer count
                viewer_count = 0
                viewer_match = re.search(r'"user_count"\s*:\s*(\d+)', html)
                if viewer_match:
                    viewer_count = int(viewer_match.group(1))

                info = LiveStreamInfo(
                    username=username,
                    room_id=room_id,
                    title=title,
                    viewer_count=viewer_count,
                    source="direct_check",
                )
                self._known_streams[username] = info
                logger.info("Found live stream: @%s (room: %s, viewers: %d)", username, room_id, viewer_count)
                return info

        except httpx.HTTPError as e:
            logger.warning("Error checking @%s live status: %s", username, e)
            return None

    async def discover_trending_lives(self) -> list[LiveStreamInfo]:
        """Attempt to discover trending/popular live streams.

        Uses TikTok's explore page and live-specific endpoints to find
        currently active streams. Note that this is best-effort as TikTok
        frequently changes their web structure.
        """
        discovered: list[LiveStreamInfo] = []

        # Strategy 1: Scrape TikTok's live explore page
        try:
            lives = await self._scrape_explore_lives()
            discovered.extend(lives)
        except Exception:
            logger.warning("Explore page scraping failed.", exc_info=True)

        # Strategy 2: Try TikTok's internal API endpoints for live streams
        try:
            lives = await self._fetch_recommended_lives()
            discovered.extend(lives)
        except Exception:
            logger.warning("Recommended lives API failed.", exc_info=True)

        # Deduplicate by username
        seen = set()
        unique: list[LiveStreamInfo] = []
        for stream in discovered:
            if stream.username not in seen:
                seen.add(stream.username)
                unique.append(stream)
                self._known_streams[stream.username] = stream

        logger.info("Discovered %d unique live streams.", len(unique))
        return unique

    async def _scrape_explore_lives(self) -> list[LiveStreamInfo]:
        """Scrape the TikTok explore/live page for active streams."""
        results: list[LiveStreamInfo] = []
        url = f"{TIKTOK_BASE}/live"

        try:
            async with httpx.AsyncClient(
                headers=BROWSER_HEADERS,
                follow_redirects=True,
                timeout=20,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug("Explore page returned status %d", resp.status_code)
                    return results

                html = resp.text
                soup = BeautifulSoup(html, "lxml")

                # Look for live stream cards / links
                live_links = soup.find_all("a", href=re.compile(r"/@[\w.]+/live"))
                for link in live_links:
                    href = link.get("href", "")
                    match = re.search(r"/@([\w.]+)/live", href)
                    if match:
                        username = match.group(1)
                        results.append(LiveStreamInfo(username=username, source="explore"))

                # Also try to extract from JSON data embedded in page
                json_matches = re.findall(r'"uniqueId"\s*:\s*"([\w.]+)"', html)
                for uid in json_matches:
                    if uid not in {r.username for r in results}:
                        results.append(LiveStreamInfo(username=uid, source="explore_json"))

        except httpx.HTTPError as e:
            logger.warning("Error scraping explore lives: %s", e)

        return results

    async def _fetch_recommended_lives(self) -> list[LiveStreamInfo]:
        """Try to fetch recommended live streams from TikTok's internal API."""
        results: list[LiveStreamInfo] = []

        api_urls = [
            f"{TIKTOK_BASE}/api/live/recommend/",
            f"{TIKTOK_BASE}/api/recommend/live/",
        ]

        for api_url in api_urls:
            try:
                async with httpx.AsyncClient(
                    headers=BROWSER_HEADERS,
                    follow_redirects=True,
                    timeout=15,
                ) as client:
                    resp = await client.get(api_url, params={"count": 30})
                    if resp.status_code != 200:
                        continue

                    data = resp.json()

                    # Try common response structures
                    lives = data.get("data", data.get("body", {}).get("data", []))
                    if isinstance(lives, dict):
                        lives = lives.get("lives", lives.get("rooms", []))

                    if not isinstance(lives, list):
                        continue

                    for item in lives:
                        username = (
                            item.get("owner", {}).get("uniqueId")
                            or item.get("uniqueId")
                            or item.get("user", {}).get("uniqueId")
                            or ""
                        )
                        if username:
                            room_id = str(item.get("roomId", item.get("room_id", "")))
                            title = item.get("title", "")
                            viewer_count = int(item.get("user_count", item.get("viewerCount", 0)))
                            results.append(
                                LiveStreamInfo(
                                    username=username,
                                    room_id=room_id,
                                    title=title,
                                    viewer_count=viewer_count,
                                    source="recommended_api",
                                )
                            )
            except Exception:
                logger.debug("API endpoint %s failed.", api_url, exc_info=True)

        return results

    async def check_multiple_users(self, usernames: list[str]) -> list[LiveStreamInfo]:
        """Check multiple users for live status concurrently."""
        import asyncio

        tasks = [self.check_user_is_live(u) for u in usernames]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        live_streams: list[LiveStreamInfo] = []
        for result in results:
            if isinstance(result, LiveStreamInfo):
                live_streams.append(result)
            elif isinstance(result, Exception):
                logger.warning("Error checking user: %s", result)

        return live_streams
