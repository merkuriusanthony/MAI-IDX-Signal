"""Pydantic API models."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class SignalOut(BaseModel):
    """Serialized trading signal."""

    id: Optional[int] = None
    symbol: str
    label: str
    score: float
    entry: float
    tp1: float
    tp2: float
    sl: float
    confidence: float
    reasons: List[str] = []
    summary: str = ""
    chart_path: str = ""
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TrackingOut(BaseModel):
    """Serialized tracking record."""

    id: Optional[int] = None
    signal_id: int
    symbol: str
    entry: float
    current_price: float
    pnl_pct: float
    status: str
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
