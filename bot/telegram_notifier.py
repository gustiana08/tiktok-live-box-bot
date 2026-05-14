"""Telegram notification module."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from bot.config import settings

logger = logging.getLogger(__name__)

# Track last notification time per stream to prevent spam
_last_notified: dict[str, float] = {}


async def send_telegram_message(text: str, parse_mode: str = "HTML") -> dict[str, Any] | None:
    """Send a message to the configured Telegram chat."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram bot token or chat ID not configured. Skipping notification.")
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
                logger.info("Telegram notification sent successfully.")
            else:
                logger.error("Telegram API error: %s", data)
            return data
    except httpx.HTTPError as e:
        logger.error("Failed to send Telegram message: %s", e)
        return None


def _can_notify(stream_key: str) -> bool:
    """Check if enough time has passed since the last notification for this stream."""
    now = time.time()
    last = _last_notified.get(stream_key, 0)
    if now - last < settings.notification_cooldown:
        return False
    _last_notified[stream_key] = now
    return True


async def notify_lucky_box(
    username: str,
    room_id: int | str,
    box_info: dict[str, Any] | None = None,
) -> None:
    """Send a lucky box detection notification to Telegram."""
    stream_key = f"{username}:{room_id}"
    if not _can_notify(stream_key):
        logger.debug("Notification cooldown active for %s, skipping.", stream_key)
        return

    live_url = f"https://www.tiktok.com/@{username}/live"

    lines = [
        "<b>KOTAK KEBERUNTUNGAN TERDETEKSI!</b>",
        "",
        f"Streamer: <b>@{username}</b>",
        f"Room ID: <code>{room_id}</code>",
    ]

    if box_info:
        if box_info.get("coins"):
            lines.append(f"Koin: {box_info['coins']}")
        if box_info.get("description"):
            lines.append(f"Info: {box_info['description']}")

    lines.extend(
        [
            "",
            f'<a href="{live_url}">Buka Live Sekarang</a>',
            "",
            f"Waktu: {time.strftime('%Y-%m-%d %H:%M:%S WIB', time.gmtime(time.time() + 7 * 3600))}",
        ]
    )

    text = "\n".join(lines)
    await send_telegram_message(text)


async def notify_bot_status(status: str, detail: str = "") -> None:
    """Send bot status notification (start/stop/error)."""
    if not settings.notify_on_start:
        return

    emoji_map = {"start": "🟢", "stop": "🔴", "error": "⚠️", "info": "ℹ️"}
    emoji = emoji_map.get(status, "ℹ️")

    text = f"{emoji} <b>TikTok Live Box Bot — {status.upper()}</b>"
    if detail:
        text += f"\n{detail}"

    await send_telegram_message(text)
