"""Market-regime detection (Phase 5.2).

Computes a single market-wide risk regime from the IHSG composite index
(^JKSE) once per scan. The regime acts as a top-level gate on signals:
in a risk-off market the same long-only momentum logic keeps firing BUYs
on every MA20 cross, so we downgrade BUY -> WATCH and surface the reason.

This is intentionally cheap: one index fetch, cached per process with a
short TTL, MA50/MA200 trend + 20d realized volatility. See
PHASE5_RESEARCH.md §1 ("Add a market-regime gate ... single highest-ROI
signal-quality change").
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

INDEX_SYMBOL = "^JKSE"
_CACHE_TTL = 60 * 30  # 30 min — matches OHLCV parquet cache

# 20d annualized realized-vol threshold above which we call the regime
# "high vol" even if the trend is still up. IHSG long-run daily vol ~1%;
# 20d annualized > ~28% is a stressed tape.
_HIGH_VOL_ANNUAL = 0.28


@dataclass
class MarketRegime:
    regime: str            # "risk_on" | "neutral" | "risk_off"
    above_ma50: bool
    above_ma200: bool
    vol_annual: float      # 20d annualized realized vol (fraction)
    index_close: float
    ok: bool               # False if index data unavailable -> fail open
    reason: str = ""

    @property
    def risk_off(self) -> bool:
        return self.regime == "risk_off"

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "above_ma50": self.above_ma50,
            "above_ma200": self.above_ma200,
            "vol_annual": round(self.vol_annual, 4),
            "index_close": round(self.index_close, 2),
            "ok": self.ok,
            "reason": self.reason,
        }


# process-level cache: (timestamp, MarketRegime)
_cache: Optional[tuple] = None


def _classify(above_ma50: bool, above_ma200: bool, vol_annual: float,
              index_close: float) -> MarketRegime:
    high_vol = vol_annual >= _HIGH_VOL_ANNUAL

    if above_ma50 and above_ma200 and not high_vol:
        regime, reason = "risk_on", "IHSG di atas MA50 & MA200, volatilitas normal"
    elif not above_ma200 or (high_vol and not above_ma50):
        # primary trend broken, or stressed tape below short-term trend
        regime = "risk_off"
        bits = []
        if not above_ma200:
            bits.append("IHSG di bawah MA200 (tren utama bearish)")
        if high_vol:
            bits.append(f"volatilitas tinggi ({vol_annual*100:.0f}% annualized)")
        if not above_ma50:
            bits.append("di bawah MA50")
        reason = "Risk-off: " + ", ".join(bits)
    else:
        regime, reason = "neutral", "IHSG campuran — sinyal tetap, tanpa downgrade"

    return MarketRegime(
        regime=regime,
        above_ma50=above_ma50,
        above_ma200=above_ma200,
        vol_annual=vol_annual,
        index_close=index_close,
        ok=True,
        reason=reason,
    )


def _fail_open(msg: str) -> MarketRegime:
    """When index data is unavailable, do not penalize signals."""
    logger.warning("[regime] index unavailable, failing open: %s", msg)
    return MarketRegime(
        regime="neutral", above_ma50=True, above_ma200=True,
        vol_annual=0.0, index_close=0.0, ok=False,
        reason=f"Regime tak terdeteksi ({msg}) — gate dimatikan",
    )


def detect_regime(use_cache: bool = True) -> MarketRegime:
    """Detect current market regime from ^JKSE. Cached per process."""
    global _cache
    now = time.time()
    if use_cache and _cache is not None and now - _cache[0] < _CACHE_TTL:
        return _cache[1]

    try:
        from app.data.fetch_yahoo import fetch_ohlcv

        df = fetch_ohlcv(INDEX_SYMBOL, period="1y", interval="1d", use_cache=use_cache)
        if df is None or df.empty or len(df) < 200:
            return _fail_open(f"insufficient index bars ({0 if df is None else len(df)})")

        close = df["close"]
        index_close = float(close.iloc[-1])
        ma50 = float(close.tail(50).mean())
        ma200 = float(close.tail(200).mean())

        rets = close.pct_change().dropna().tail(20)
        vol_daily = float(rets.std()) if len(rets) else 0.0
        vol_annual = vol_daily * (252 ** 0.5)

        regime = _classify(
            above_ma50=index_close > ma50,
            above_ma200=index_close > ma200,
            vol_annual=vol_annual,
            index_close=index_close,
        )
    except Exception as exc:  # never break a scan over regime detection
        return _fail_open(str(exc))

    _cache = (now, regime)
    logger.info("[regime] %s | close=%.0f ma50=%s ma200=%s vol=%.0f%%",
                regime.regime, regime.index_close, regime.above_ma50,
                regime.above_ma200, regime.vol_annual * 100)
    return regime


def apply_regime_gate(action: str, regime: MarketRegime) -> tuple:
    """Downgrade an action under a risk-off regime.

    Returns (new_action, gated: bool, note: str). Only BUY is suppressed
    (downgraded to WATCH); WATCH/HOLD/AVOID/DANGER are untouched. Fails
    open: if regime data was unavailable, nothing is changed.
    """
    if not regime.ok or not regime.risk_off:
        return action, False, ""
    if action == "BUY":
        return "WATCH", True, "BUY → WATCH (pasar risk-off): " + regime.reason
    return action, False, ""
