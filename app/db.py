"""Async SQLAlchemy database layer (SQLite via aiosqlite)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings


class Base(DeclarativeBase):
    pass


class Signal(Base):
    """A generated trading signal."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    label: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    entry: Mapped[float] = mapped_column(Float, default=0.0)
    tp1: Mapped[float] = mapped_column(Float, default=0.0)
    tp2: Mapped[float] = mapped_column(Float, default=0.0)
    sl: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reasons: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    chart_path: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )


class Tracking(Base):
    """Tracks how a signal performed after issue."""

    __tablename__ = "tracking"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    entry: Mapped[float] = mapped_column(Float, default=0.0)
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables if they do not exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Yield an async session (FastAPI dependency)."""
    async with async_session() as session:
        yield session
