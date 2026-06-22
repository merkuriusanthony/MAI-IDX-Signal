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
    TELEGRAM_GROUP_ID: str = "-1004352444069"
    WHATSAPP_ENABLED: bool = False

    # Storage
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/signals.db"

    # Data sources
    STOCKBIT_SESSION_COOKIE: str = ""
    IDX_UNIVERSE_PATH: str = "/opt/data/idx_universe.txt"

    # Charts
    CHART_DIR: str = "./data/charts"

    # Scanner
    SCAN_CONCURRENCY: int = 20
    SCAN_TOP_N: int = 5
    SCAN_MIN_AVG_VALUE: float = 1_000_000_000  # 1B IDR
    SCAN_MIN_HISTORY_DAYS: int = 60
    SCAN_DEV_LIMIT: int = 0  # 0 = no limit; set >0 for dev

    # AI (Anthropic-compatible endpoint, e.g. 9Router)
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_AUTH_TOKEN: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-6"

    # Ops
    LOG_LEVEL: str = "INFO"
    ENABLE_SCHEDULER: bool = True
    ENABLE_BOT_POLLING: bool = True

    def effective_telegram_chat_id(self) -> str:
        """Return TELEGRAM_CHAT_ID falling back to TELEGRAM_GROUP_ID."""
        return self.TELEGRAM_CHAT_ID or self.TELEGRAM_GROUP_ID


settings = Settings()
