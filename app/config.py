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
    SCAN_CONCURRENCY: int = 24  # I/O-bound worker-pool size (fetches run in threads)
    SCAN_TOP_N: int = 5
    SCAN_MIN_AVG_VALUE: float = 1_000_000_000  # 1B IDR
    SCAN_MIN_HISTORY_DAYS: int = 60
    SCAN_DEV_LIMIT: int = 0  # 0 = no limit; set >0 for dev
    # Per-symbol fetch timeout (seconds). A slow/hung yfinance call is
    # abandoned after this so one bad symbol can't stall a worker.
    SCAN_FETCH_TIMEOUT: float = 25.0
    # Inter-fetch throttle per worker (milliseconds). Spreads request bursts
    # so hammering ~800 symbols fast doesn't trip Yahoo rate-limiting. 0=off.
    SCAN_THROTTLE_MS: int = 0
    # Persist live scan progress every N scanned symbols (crash-recoverable).
    SCAN_CHECKPOINT_INTERVAL: int = 25

    # Universe auto-update (daily IPO/delisting sync)
    UNIVERSE_AUTOUPDATE_ENABLED: bool = True
    UNIVERSE_BACKUP_DIR: str = ""  # default: <universe dir>/universe_backups
    UNIVERSE_CHANGES_LOG: str = ""  # default: <universe dir>/universe_changes.jsonl
    # Abort the update if the freshly-fetched list is < this fraction of the
    # current universe size (guards against a partial/garbage upstream fetch).
    UNIVERSE_MIN_RATIO: float = 0.80
    IDX_LISTED_URL: str = (
        "https://www.idx.co.id/primary/StockData/GetSecuritiesStock"
        "?start=0&length=9999&code=&sector=&board=&language=en-us"
    )
    # Cloudflare Worker proxy that fronts IDX_LISTED_URL from a non-DC IP.
    # Empty = call IDX directly (blocked from datacenter/NAS IPs).
    IDX_PROXY_URL: str = ""
    STOCKBIT_UNIVERSE_URL: str = "https://exodus.stockbit.com/findata-view/company/list"
    # Authenticated search endpoint used to enumerate the full IDX universe.
    STOCKBIT_SEARCH_URL: str = "https://exodus.stockbit.com/search/v2"
    # Path (inside container) to a file holding a fresh Stockbit access JWT,
    # written by the host token manager's daily refresh. Mounted via ./data.
    STOCKBIT_ACCESS_FILE: str = "/app/data/.stockbit_access"

    # AI (Anthropic-compatible endpoint, e.g. 9Router)
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_AUTH_TOKEN: str = ""
    CLAUDE_MODEL: str = "cc/claude-opus-4-8"
    # Phase 5.4: cheap model for per-symbol news classification fan-out.
    CLAUDE_HAIKU_MODEL: str = "cc/claude-haiku-4-5-20251001"
    # Decision model: verdict + final analysis MUST use opus (high stakes).
    CLAUDE_DECISION_MODEL: str = "cc/claude-opus-4-8"
    # AI gating: let Claude's verdict/sentiment actually move the action.
    AI_VERDICT_ENABLED: bool = True   # verdict=reject downgrades BUY->WATCH
    AI_NEWS_ENABLED: bool = True      # fetch + classify news per top candidate
    NEWS_LOOKBACK_DAYS: int = 7
    NEWS_MAX_ITEMS: int = 6
    NEWS_CACHE_TTL: int = 60 * 60     # 1h per-symbol news cache

    # Access control
    ADMIN_TELEGRAM_ID: int = 0
    ADMIN_KEY: str = ""

    # Ops
    LOG_LEVEL: str = "INFO"
    ENABLE_SCHEDULER: bool = True
    ENABLE_BOT_POLLING: bool = True

    def effective_admin_key(self) -> str:
        """Return ADMIN_KEY, generating a random one if unset (per-process)."""
        if not self.ADMIN_KEY:
            import uuid
            self.ADMIN_KEY = uuid.uuid4().hex
        return self.ADMIN_KEY

    def effective_telegram_chat_id(self) -> str:
        """Return TELEGRAM_CHAT_ID falling back to TELEGRAM_GROUP_ID."""
        return self.TELEGRAM_CHAT_ID or self.TELEGRAM_GROUP_ID


settings = Settings()
