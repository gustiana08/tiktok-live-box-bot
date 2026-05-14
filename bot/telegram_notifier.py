"""Telegram notification module."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from bot.config import settings

logger = logging.getLogger(__name__)

_last_notified: dict[str, float] = {}


async def send_telegram_message(text: str, parse_mode: str = "HTML") -> dict[str, Any] | None:
    """Send a message to the configured Telegram chat."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram bot token or chat ID not configured.")
        return None

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("ok"):
                logger.info("Telegram notification sent.")
            else:
                logger.error("Telegram API error: %s", data)
            return data
    except httpx.HTTPError as e:
        logger.error("Failed to send Telegram message: %s", e)
        return None


def _can_notify(stream_key: str) -> bool:
    """Check cooldown for this stream."""
    now = time.time()
    last = _last_notified.get(stream_key, 0)
    if now - last < settings.notification_cooldown:
        return False
    _last_notified[stream_key] = now
    return True


def _wib_now() -> str:
    """Current time in WIB (UTC+7)."""
    return time.strftime("%H:%M:%S WIB", time.gmtime(time.time() + 7 * 3600))


async def notify_lucky_box(
    username: str,
    room_id: int | str,
    box_info: dict[str, Any] | None = None,
) -> None:
    """Send a lucky box notification — short format with account info + region."""
    stream_key = f"{username}:{room_id}"
    if not _can_notify(stream_key):
        logger.debug("Cooldown active for %s, skipping.", stream_key)
        return

    live_url = f"https://www.tiktok.com/@{username}/live"
    si = (box_info or {}).get("stream_info", {})

    nickname = si.get("nickname", "")
    region = si.get("region", "-")
    viewers = si.get("viewer_count", 0)
    title = si.get("title", "")

    name_display = f"{nickname} (@{username})" if nickname else f"@{username}"

    lines = [
        "🎁 <b>KOTAK KEBERUNTUNGAN!</b>",
        "",
        f"👤 {name_display}",
        f"🌍 Region: <b>{region or '-'}</b>",
        f"👀 Viewers: <b>{viewers}</b>",
    ]

    if title:
        lines.append(f"📺 {title}")

    lines.append("")
    lines.append(f"🔗 {live_url}")
    lines.append(f"⏰ {_wib_now()}")

    await send_telegram_message("\n".join(lines))


async def notify_bot_status(status: str, detail: str = "") -> None:
    """Send bot status notification."""
    if not settings.notify_on_start:
        return

    emoji_map = {"start": "🟢", "stop": "🔴", "error": "⚠️", "info": "ℹ️"}
    emoji = emoji_map.get(status, "ℹ️")

    text = f"{emoji} <b>TikTok Box Bot — {status.upper()}</b>"
    if detail:
        text += f"\n{detail}"

    await send_telegram_message(text)


async def notify_live_found(
    username: str,
    room_id: int | str,
    stream_info: dict[str, Any] | None = None,
) -> None:
    """Send notification when a live stream with potential box is found — short format."""
    live_url = f"https://www.tiktok.com/@{username}/live"
    si = stream_info or {}

    nickname = si.get("nickname", "")
    region = si.get("region", "-")
    viewers = si.get("viewer_count", 0)
    title = si.get("title", "")

    name_display = f"{nickname} (@{username})" if nickname else f"@{username}"

    lines = [
        "📡 <b>LIVE TERDETEKSI</b>",
        "",
        f"👤 {name_display}",
        f"🌍 Region: <b>{region or '-'}</b>",
        f"👀 Viewers: <b>{viewers}</b>",
    ]

    if title:
        lines.append(f"📺 {title}")

    lines.append("")
    lines.append(f"🔗 {live_url}")
    lines.append(f"⏰ {_wib_now()}")

    await send_telegram_message("\n".join(lines))
