"""ScannerService: orchestrates universe scan end-to-end."""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from app.analytics.indicators import compute_features
from app.analytics.regime import apply_regime_gate, detect_regime
from app.analytics.scoring import gorengan_penalty, score_snapshot
from app.config import settings
from app.data.fetch_yahoo import df_to_ohlcv_rows, fetch_ohlcv_safe
from app.data.universe import load_universe
from app.db import (
    create_scan_run,
    finish_scan_run,
    save_ohlcv,
    save_scan_candidate,
    save_signal_dict,
)
from app.signals.chart import generate_chart
from app.signals.generator import _build_one

logger = logging.getLogger(__name__)

SCAN_MODES = {"premarket", "opening", "intraday", "midday", "closing", "eod", "manual"}


class ScannerService:
    """Full pipeline: universe → fetch → score → candidates → signals."""

    def __init__(
        self,
        mode: str = "manual",
        limit: Optional[int] = None,
        top_n: Optional[int] = None,
        concurrency: Optional[int] = None,
        with_ai: bool = False,
        generate_charts: bool = True,
    ):
        self.mode = mode if mode in SCAN_MODES else "manual"
        self.top_n = top_n or settings.SCAN_TOP_N
        self.with_ai = with_ai
        self.generate_charts = generate_charts
        self.concurrency = concurrency or settings.SCAN_CONCURRENCY

        universe = load_universe()
        dev_limit = settings.SCAN_DEV_LIMIT
        if limit:
            universe = universe[:limit]
        elif dev_limit > 0:
            universe = universe[:dev_limit]
        self.universe = universe

    # ------------------------------------------------------------------

    async def run(self) -> Dict:
        """Execute full scan, return summary dict."""
        universe_count = len(self.universe)
        scan_run_id = await create_scan_run(self.mode, universe_count)
        logger.info("[scanner] run_id=%d mode=%s universe=%d", scan_run_id, self.mode, universe_count)

        scanned = 0
        passed = 0
        failed = 0
        candidates: List[Dict] = []
        error_msg = None

        try:
            sem = asyncio.Semaphore(self.concurrency)

            # Phase 5.2: detect market regime once per scan (IHSG ^JKSE).
            # Fetch is blocking yfinance -> run in executor. Fails open.
            loop = asyncio.get_event_loop()
            regime = await loop.run_in_executor(None, detect_regime)
            logger.info("[scanner] regime=%s ok=%s reason=%s",
                        regime.regime, regime.ok, regime.reason)

            async def _process(symbol: str) -> Optional[Dict]:
                nonlocal scanned, passed, failed
                async with sem:
                    result = fetch_ohlcv_safe(symbol)
                    scanned += 1
                    if scanned % 100 == 0:
                        logger.info("[scanner] progress %d/%d", scanned, universe_count)
                    if not result["ok"]:
                        failed += 1
                        return None

                    df = result["df"]
                    # cache to SQLite
                    try:
                        rows = df_to_ohlcv_rows(symbol, df)
                        await save_ohlcv(symbol, rows)
                    except Exception as exc:
                        logger.debug("ohlcv cache error %s: %s", symbol, exc)

                    snap = compute_features(df, symbol=symbol)
                    if not snap.data_ok:
                        failed += 1
                        return None

                    # liquidity pre-filter
                    value_est = result["value_estimate"]
                    if value_est < settings.SCAN_MIN_AVG_VALUE and settings.SCAN_MIN_AVG_VALUE > 0:
                        failed += 1
                        return None

                    score_dict = score_snapshot(snap)

                    # anti-gorengan penalty
                    daily_change = 0.0
                    if len(df) >= 2 and df["close"].iloc[-2]:
                        daily_change = (
                            df["close"].iloc[-1] - df["close"].iloc[-2]
                        ) / df["close"].iloc[-2]
                    penalty = gorengan_penalty({
                        "close": snap.close,
                        "avg_value_20d": value_est,
                        "volume_ratio": snap.volume_ratio,
                        "atr_pct": (snap.atr_pct or 0) / 100.0,
                        "daily_change_pct": daily_change,
                    })
                    final_score = max(0.0, score_dict["score"] - penalty)

                    # Phase 5.2: market-regime gate. In a risk-off tape,
                    # downgrade BUY -> WATCH so we stop firing longs into a
                    # falling market. Fails open if regime undetected.
                    gated_action, was_gated, gate_note = apply_regime_gate(
                        score_dict["action"], regime
                    )
                    reason_codes = list(score_dict.get("reason_codes", []))
                    if was_gated:
                        reason_codes.append("REGIME_RISK_OFF")

                    candidate = {
                        "symbol": symbol,
                        "score": final_score,
                        "action": gated_action,
                        "close": snap.close,
                        "volume": int(snap.volume_latest),
                        "value_estimate": value_est,
                        "rsi": snap.rsi14 or 0,
                        "ma20": snap.ma20 or 0,
                        "ma50": snap.ma50 or 0,
                        "ma100": snap.ma100 or 0,
                        "ma200": snap.ma200 or 0,
                        "volume_ratio": snap.volume_ratio,
                        "risk_score": 0.0,
                        "reason_codes": reason_codes,
                        "regime": regime.regime,
                        "regime_gated": was_gated,
                        "snapshot": snap.to_dict(),
                        "_df": df,
                        "_snap": snap,
                    }
                    passed += 1
                    return candidate

            tasks = [_process(sym) for sym in self.universe]
            results = await asyncio.gather(*tasks, return_exceptions=False)

            for r in results:
                if r is not None:
                    candidates.append(r)

            # save all candidates
            for cand in candidates:
                try:
                    await save_scan_candidate(scan_run_id, cand)
                except Exception as exc:
                    logger.warning("save_candidate error: %s", exc)

            # sort by score and take top_n for full signal generation
            candidates.sort(key=lambda c: c["score"], reverse=True)
            top_candidates = candidates[: self.top_n]

            signals: List[Dict] = []
            for cand in top_candidates:
                try:
                    sig = await _build_one(
                        cand["symbol"],
                        with_ai=self.with_ai,
                        min_history=settings.SCAN_MIN_HISTORY_DAYS,
                        precomputed_df=cand.get("_df"),
                        precomputed_snap=cand.get("_snap"),
                        precomputed_value=cand.get("value_estimate"),
                    )
                    if sig is None:
                        continue
                    if self.generate_charts:
                        df = cand.get("_df")
                        if df is not None:
                            chart_path = generate_chart(cand["symbol"], df, sig)
                            sig["chart_path"] = chart_path
                    sig_id = await save_signal_dict(sig, scan_run_id=scan_run_id)
                    sig["id"] = sig_id
                    signals.append(sig)
                except Exception as exc:
                    logger.warning("signal build error for %s: %s", cand["symbol"], exc)

            await finish_scan_run(
                scan_run_id, "success",
                scanned=scanned, passed=passed, failed=failed,
            )
            logger.info(
                "[scanner] done run_id=%d scanned=%d passed=%d signals=%d",
                scan_run_id, scanned, passed, len(signals),
            )
            return {
                "scan_run_id": scan_run_id,
                "mode": self.mode,
                "universe_count": universe_count,
                "scanned": scanned,
                "passed": passed,
                "failed": failed,
                "regime": regime.to_dict(),
                "top_signals": signals,
                "status": "success",
            }

        except Exception as exc:
            error_msg = str(exc)
            logger.error("[scanner] run error: %s", exc, exc_info=True)
            await finish_scan_run(
                scan_run_id, "failed",
                scanned=scanned, passed=passed, failed=failed, error=error_msg,
            )
            return {
                "scan_run_id": scan_run_id,
                "mode": self.mode,
                "status": "failed",
                "error": error_msg,
                "top_signals": [],
            }
