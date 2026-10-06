"""Phase 5.5: foreign (asing) broker flow as a scoring confirmation layer.

Foreign net buy/sell data was already fetched for top-N candidates
(signals/generator.py -> fetch_foreign_flow) and displayed on charts/
dashboard, but never fed back into the score itself. A Phase 5.2 comment
in scoring.py explicitly removed a hardcoded "+7 flow bucket" because it
was a constant applied to every stock regardless of actual flow -- zero
discrimination. This module replaces that with a real signal computed
from the fetched daily foreign_net series.

Deliberately cheap/no new fetches: runs only on the already-fetched
top-N foreign_df (same cost envelope as the AI veto layer), never in the
full-universe scoring loop (app/scanner.py _process) -- that path hit the
Stockbit keystats rate limiter (burst 3 / 34s cooldown, see #3 fix) and
cannot afford a per-symbol deep fetch across 900+ tickers.

Bounded to +/-8 so it confirms/tempers the base score, never dominates
it (same pattern as app/analytics/archetype.py's +/-12 archetype_adjust).
Fails open: missing/empty data -> no adjustment, never raises.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

_ADJ_CAP = 8.0
_LOOKBACK_DAYS = 5
_STRONG_RATIO = 0.6   # net flow >= 60% of gross traded value = decisive


def foreign_flow_adjust(
    foreign_df: Optional[pd.DataFrame], action: str, base_score: float
) -> Tuple[float, list, list]:
    """Return (adjusted_score, extra_reasons, extra_codes).

    Looks at the last _LOOKBACK_DAYS of foreign_net (already fetched).
    A BUY confirmed by decisive foreign net buying gets a small boost;
    a BUY fighting decisive foreign net selling gets tempered. WATCH/
    HOLD/AVOID/DANGER are left untouched (same scope as the regime gate
    and MTF filter -- only BUY is actionable here).
    """
    if action != "BUY" or foreign_df is None or foreign_df.empty:
        return base_score, [], []
    if "foreign_net" not in foreign_df.columns:
        return base_score, [], []

    try:
        tail = pd.to_numeric(foreign_df["foreign_net"], errors="coerce").dropna().tail(_LOOKBACK_DAYS)
        if tail.empty:
            return base_score, [], []
        net_sum = float(tail.sum())

        gross = None
        if "foreign_buy" in foreign_df.columns and "foreign_sell" in foreign_df.columns:
            buy = pd.to_numeric(foreign_df["foreign_buy"], errors="coerce").dropna().tail(_LOOKBACK_DAYS)
            sell = pd.to_numeric(foreign_df["foreign_sell"], errors="coerce").dropna().tail(_LOOKBACK_DAYS)
            gross = float(buy.sum() + sell.sum())
    except Exception as exc:
        logger.debug("foreign_flow_adjust parse error: %s", exc)
        return base_score, [], []

    if not gross or gross <= 0:
        return base_score, [], []

    ratio = net_sum / gross  # signed strength of net flow vs total traded value
    adj = 0.0
    reasons: list = []
    codes: list = []

    if ratio >= _STRONG_RATIO:
        adj = _ADJ_CAP
        reasons.append(f"Asing net buy kuat {_LOOKBACK_DAYS}D, mengonfirmasi BUY")
        codes.append("FLOW_FOREIGN_BUY_STRONG")
    elif ratio > 0:
        adj = _ADJ_CAP * (ratio / _STRONG_RATIO)
        reasons.append(f"Asing net buy {_LOOKBACK_DAYS}D, mendukung BUY")
        codes.append("FLOW_FOREIGN_BUY")
    elif ratio <= -_STRONG_RATIO:
        adj = -_ADJ_CAP
        reasons.append(f"Asing net sell kuat {_LOOKBACK_DAYS}D, BUY berlawanan arus asing")
        codes.append("FLOW_FOREIGN_SELL_STRONG")
    elif ratio < 0:
        adj = -_ADJ_CAP * (abs(ratio) / _STRONG_RATIO)
        reasons.append(f"Asing net sell {_LOOKBACK_DAYS}D, perhatikan arus keluar")
        codes.append("FLOW_FOREIGN_SELL")

    if adj == 0.0:
        return base_score, [], []

    adj = max(-_ADJ_CAP, min(_ADJ_CAP, adj))
    new_score = max(0.0, min(100.0, base_score + adj))
    return round(new_score, 1), reasons, codes
