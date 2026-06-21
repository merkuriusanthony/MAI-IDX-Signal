"""FastAPI application entrypoint for MAI-IDX-Signal."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.dashboard.routes import router as dashboard_router
from app.db import init_db
from app.signals.routes import chart_router, scan_router, signals_router

VERSION = "0.2.0"

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup."""
    os.makedirs(settings.CHART_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)
    await init_db()
    yield


app = FastAPI(title="MAI-IDX-Signal", version=VERSION, lifespan=lifespan)

app.include_router(signals_router)
app.include_router(scan_router)
app.include_router(chart_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health():
    """Liveness probe."""
    return {"status": "ok", "version": VERSION}


@app.get("/api/health")
async def api_health():
    return {"status": "ok", "version": VERSION}
