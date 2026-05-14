"""Configuration management using pydantic-settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # TikTok
    tiktok_usernames: str = ""
    scan_interval: int = 30
    max_concurrent_streams: int = 10

    # Notification
    notify_on_start: bool = True
    notification_cooldown: int = 300

    # Logging
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def username_list(self) -> list[str]:
        """Parse comma-separated usernames into a list."""
        if not self.tiktok_usernames.strip():
            return []
        return [u.strip().lstrip("@") for u in self.tiktok_usernames.split(",") if u.strip()]


settings = Settings()
