"""FastAPI application entrypoint for MAI-IDX-Signal."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.backtest.routes import router as backtest_router
from app.dashboard.routes import router as dashboard_router
from app.db import init_db
from app.pages.admin import router as admin_router
from app.pages.landing import router as landing_router
from app.pages.member import router as member_router
from app.signals.routes import chart_router, scan_router, signals_router

VERSION = "0.6.0"

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

# Global references for graceful shutdown
_bot_app = None
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB, Telegram bot, and scheduler on startup."""
    global _bot_app, _scheduler

    # 1. Storage dirs
    os.makedirs(settings.CHART_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)

    # 2. DB
    await init_db()

    # 3. Telegram bot (non-blocking PTB v20)
    # Use ENABLE_BOT_POLLING=false when another process owns the same token
    if settings.ENABLE_BOT_POLLING:
        try:
            from app.bots.telegram import start_bot, token_is_valid
            if token_is_valid(settings.TELEGRAM_BOT_TOKEN):
                _bot_app = await start_bot()
                if _bot_app:
                    logger.info("Telegram bot started (polling)")
                else:
                    logger.warning("Telegram bot failed to start (start_bot returned None)")
            else:
                logger.info("Telegram bot disabled (no token)")
        except Exception as exc:
            logger.warning("Telegram bot startup error (non-fatal): %s", exc)
    else:
        logger.info("Telegram bot polling disabled (ENABLE_BOT_POLLING=false) — outbound send still active")

    # 4. APScheduler
    if settings.ENABLE_SCHEDULER:
        try:
            from app.scheduler.jobs import build_scheduler
            _scheduler = build_scheduler()
            _scheduler.start()
            logger.info("Scheduler started — jobs: %s", [j.id for j in _scheduler.get_jobs()])
        except Exception as exc:
            logger.warning("Scheduler startup error (non-fatal): %s", exc)
    else:
        logger.info("Scheduler disabled (ENABLE_SCHEDULER=false)")

    yield

    # Shutdown
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    if _bot_app:
        try:
            await _bot_app.updater.stop()
            await _bot_app.stop()
            await _bot_app.shutdown()
            logger.info("Telegram bot stopped")
        except Exception as exc:
            logger.warning("Telegram bot shutdown error: %s", exc)


app = FastAPI(title="MAI-IDX-Signal", version=VERSION, lifespan=lifespan)

app.include_router(signals_router)
app.include_router(scan_router)
app.include_router(chart_router)
app.include_router(dashboard_router)
app.include_router(backtest_router)
app.include_router(landing_router)
app.include_router(member_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    """Liveness probe."""
    return {"status": "ok", "version": VERSION}


@app.get("/api/health")
async def api_health():
    return {"status": "ok", "version": VERSION}


@app.get("/api/status")
async def api_status():
    """Operational status: version, DB connectivity, key table presence,
    latest signal/scan metadata, and scheduler flag."""
    from app.db import get_db_status

    db_status = await get_db_status()
    return {
        "status": "ok" if db_status.get("connected") else "degraded",
        "version": VERSION,
        "scheduler_enabled": settings.ENABLE_SCHEDULER,
        "bot_polling_enabled": settings.ENABLE_BOT_POLLING,
        "database": db_status,
    }
