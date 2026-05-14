"""TikTok Live stream discovery module.

Discovers currently active TikTok Live streams via multiple strategies:
1. Playwright-based browser scraping (JS-rendered pages)
2. TikTokLive library room check
3. HTTP-based scraping (fallback)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TIKTOK_BASE = "https://www.tiktok.com"

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
        """Check if a specific user is currently live using TikTokLive library."""
        username = username.lstrip("@")

        # Strategy 1: Use TikTokLive library to check room status
        try:
            info = await self._check_via_tiktoklive(username)
            if info:
                return info
        except Exception:
            logger.debug("TikTokLive check failed for @%s, trying HTTP.", username)

        # Strategy 2: HTTP scrape fallback
        return await self._check_via_http(username)

    async def _check_via_tiktoklive(self, username: str) -> LiveStreamInfo | None:
        """Use TikTokLive library to check if user is live."""
        from TikTokLive import TikTokLiveClient

        client = TikTokLiveClient(unique_id=f"@{username}")
        try:
            # Try to fetch room info without fully connecting
            await client.start(fetch_room_info=True)
            room_id = str(client.room_id) if client.room_id else ""
            title = ""
            viewer_count = 0
            if client.room_info:
                title = client.room_info.get("title", "")
                viewer_count = int(client.room_info.get("user_count", 0))

            await client.disconnect()

            if room_id:
                info = LiveStreamInfo(
                    username=username,
                    room_id=room_id,
                    title=title,
                    viewer_count=viewer_count,
                    source="tiktoklive_lib",
                )
                self._known_streams[username] = info
                logger.info("@%s is LIVE (room: %s, viewers: %d)", username, room_id, viewer_count)
                return info
        except Exception as e:
            logger.debug("TikTokLive room check for @%s: %s", username, e)
            try:
                await client.disconnect()
            except Exception:
                pass
        return None

    async def _check_via_http(self, username: str) -> LiveStreamInfo | None:
        """Check if a user is live via HTTP scraping."""
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

                room_match = re.search(r'"roomId"\s*:\s*"(\d+)"', html)
                if not room_match:
                    room_match = re.search(r"room_id[=:](\d+)", html)

                if not room_match:
                    logger.debug("@%s is not live or room ID not found.", username)
                    return None

                room_id = room_match.group(1)
                title = ""
                title_match = re.search(r'"title"\s*:\s*"([^"]*)"', html)
                if title_match:
                    title = title_match.group(1)

                viewer_count = 0
                viewer_match = re.search(r'"user_count"\s*:\s*(\d+)', html)
                if viewer_match:
                    viewer_count = int(viewer_match.group(1))

                info = LiveStreamInfo(
                    username=username,
                    room_id=room_id,
                    title=title,
                    viewer_count=viewer_count,
                    source="http_scrape",
                )
                self._known_streams[username] = info
                logger.info("Found live stream: @%s (room: %s, viewers: %d)", username, room_id, viewer_count)
                return info

        except httpx.HTTPError as e:
            logger.warning("Error checking @%s live status: %s", username, e)
            return None

    async def discover_trending_lives(self) -> list[LiveStreamInfo]:
        """Discover trending/popular live streams using multiple strategies."""
        discovered: list[LiveStreamInfo] = []

        # Strategy 1: Playwright browser-based discovery (best results)
        try:
            lives = await self._discover_via_playwright()
            discovered.extend(lives)
        except Exception:
            logger.debug("Playwright discovery failed.", exc_info=True)

        # Strategy 2: HTTP-based scraping (fallback)
        try:
            lives = await self._scrape_explore_lives()
            discovered.extend(lives)
        except Exception:
            logger.debug("HTTP explore scraping failed.", exc_info=True)

        # Strategy 3: Internal API endpoints
        try:
            lives = await self._fetch_recommended_lives()
            discovered.extend(lives)
        except Exception:
            logger.debug("Recommended lives API failed.", exc_info=True)

        # Deduplicate by username
        seen: set[str] = set()
        unique: list[LiveStreamInfo] = []
        for stream in discovered:
            if stream.username not in seen:
                seen.add(stream.username)
                unique.append(stream)
                self._known_streams[stream.username] = stream

        logger.info("Discovered %d unique live streams.", len(unique))
        return unique

    async def _discover_via_playwright(self) -> list[LiveStreamInfo]:
        """Use Playwright to discover live streams from multiple regions."""
        results: list[LiveStreamInfo] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.debug("Playwright not installed, skipping browser-based discovery.")
            return results

        # Scan multiple pages: global + Indonesian locale
        pages_to_scan = [
            f"{TIKTOK_BASE}/live",
            f"{TIKTOK_BASE}/live?lang=id-ID",
        ]

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp("http://localhost:29229")
                context = browser.contexts[0] if browser.contexts else await browser.new_context()

                for page_url in pages_to_scan:
                    page = await context.new_page()
                    try:
                        await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(5000)

                        for _ in range(5):
                            await page.evaluate("window.scrollBy(0, 800)")
                            await page.wait_for_timeout(1000)

                        content = await page.content()
                        username_pattern = re.compile(r"/@([\w.]+)/live")
                        found_usernames = set(username_pattern.findall(content))

                        scripts = await page.query_selector_all("script")
                        for script in scripts:
                            try:
                                text = await script.inner_text()
                            except Exception:
                                continue
                            if "uniqueId" in text or "roomId" in text:
                                json_usernames = re.findall(r'"uniqueId"\s*:\s*"([\w.]+)"', text)
                                found_usernames.update(json_usernames)
                                room_ids = re.findall(r'"roomId"\s*:\s*"(\d+)"', text)
                                for uid, rid in zip(json_usernames, room_ids, strict=False):
                                    results.append(
                                        LiveStreamInfo(
                                            username=uid,
                                            room_id=rid,
                                            source="playwright_json",
                                        )
                                    )

                        existing = {r.username for r in results}
                        for uname in found_usernames:
                            if uname not in existing:
                                results.append(LiveStreamInfo(username=uname, source="playwright_link"))
                    except Exception as e:
                        logger.debug("Playwright page %s error: %s", page_url, e)
                    finally:
                        await page.close()

                logger.info("Playwright discovered %d live streams.", len(results))

        except Exception as e:
            logger.debug("Playwright discovery error: %s", e)

        return results

    async def _scrape_explore_lives(self) -> list[LiveStreamInfo]:
        """Scrape the TikTok explore/live page via HTTP."""
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
                    return results

                html = resp.text
                soup = BeautifulSoup(html, "lxml")

                live_links = soup.find_all("a", href=re.compile(r"/@[\w.]+/live"))
                for link in live_links:
                    href = link.get("href", "")
                    match = re.search(r"/@([\w.]+)/live", href)
                    if match:
                        results.append(LiveStreamInfo(username=match.group(1), source="explore"))

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
        tasks = [self.check_user_is_live(u) for u in usernames]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        live_streams: list[LiveStreamInfo] = []
        for result in results:
            if isinstance(result, LiveStreamInfo):
                live_streams.append(result)
            elif isinstance(result, Exception):
                logger.warning("Error checking user: %s", result)

        return live_streams
