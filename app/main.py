"""FastAPI application entrypoint for MAI-IDX-Signal."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.config import settings
from app.dashboard.routes import router as dashboard_router
from app.db import init_db
from app.signals.routes import chart_router, scan_router, signals_router

VERSION = "0.2.0"

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Init DB, start the Telegram bot and scheduler; tear down on exit."""
    os.makedirs(settings.CHART_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)
    await init_db()

    # --- Telegram bot (non-blocking) ---
    bot_app = None
    try:
        from app.bots.telegram import start_bot
        bot_app = await start_bot()
    except Exception as exc:
        logger.warning("Telegram bot init error: %s", exc)

    # --- Scheduler ---
    scheduler = None
    if settings.ENABLE_SCHEDULER:
        try:
            from app.scheduler.jobs import build_scheduler
            scheduler = build_scheduler()
            scheduler.start()
            logger.info("Scheduler started")
        except Exception as exc:
            logger.warning("Scheduler failed to start: %s", exc)
    else:
        logger.info("Scheduler disabled (ENABLE_SCHEDULER=false)")

    try:
        yield
    finally:
        if scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
                logger.info("Scheduler stopped")
            except Exception as exc:
                logger.warning("Scheduler shutdown error: %s", exc)
        try:
            from app.bots.telegram import stop_bot
            await stop_bot(bot_app)
        except Exception as exc:
            logger.warning("Telegram bot shutdown error: %s", exc)


app = FastAPI(title="MAI-IDX-Signal", version=VERSION, lifespan=lifespan)

app.include_router(signals_router)
app.include_router(scan_router)
app.include_router(chart_router)
app.include_router(dashboard_router)


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to the dashboard."""
    return RedirectResponse(url="/dashboard")


@app.get("/health")
async def health():
    """Liveness probe."""
    return {"status": "ok", "version": VERSION}


@app.get("/api/health")
async def api_health():
    return {"status": "ok", "version": VERSION}
