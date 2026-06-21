"""Application settings loaded from environment / .env file."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for MAI-IDX-Signal."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Delivery
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    WHATSAPP_ENABLED: bool = False

    # Storage
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/signals.db"

    # Data sources
    STOCKBIT_SESSION_COOKIE: str = ""
    IDX_UNIVERSE_PATH: str = "/opt/data/idx_universe.txt"

    # AI (Anthropic-compatible endpoint, e.g. 9Router)
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_AUTH_TOKEN: str = ""
    CLAUDE_MODEL: str = "claude-opus-4-8"

    # Ops
    LOG_LEVEL: str = "INFO"


settings = Settings()
