"""Shared fundamental verdict / formatting logic.

Single source of truth for chart table (chart.py), dashboard detail
(dashboard/routes.py), and /api/analyze. Keeps verdict directions and number
formatting from diverging between renderers.
"""
from __future__ import annotations

from typing import Dict, Optional

# Industry benchmark (Appendix B). pct fields stored as plain percent numbers.
BENCHMARK = {
    "per": 14.0,
    "pbv": 1.8,
    "roe": 14.0,
    "roa": 5.0,
    "net_margin": 10.0,
}

# In-line band: ±15% around benchmark.
_BAND = 0.15

# Metrics where a LOWER value is better (cheap valuation).
_LOWER_BETTER = {"per", "pbv"}
# Metrics where a HIGHER value is better.
_HIGHER_BETTER = {"roe", "roa", "net_margin"}


def verdict(metric: str, value: Optional[float]) -> str:
    """Return '+' (good), '!' (bad), '=' (in-line), or '' (no benchmark/None).

    Direction-aware: PER/PBV lower-is-better, ROE/ROA/NM higher-is-better.
    """
    bench = BENCHMARK.get(metric)
    if bench is None or value is None:
        return ""
    try:
        v = float(value)
    except Exception:
        return ""
    lo, hi = bench * (1 - _BAND), bench * (1 + _BAND)
    if metric in _LOWER_BETTER:
        if v < lo:
            return "+"
        if v > hi:
            return "!"
        return "="
    if metric in _HIGHER_BETTER:
        if v > hi:
            return "+"
        if v < lo:
            return "!"
        return "="
    return ""


def fmt(value: Optional[float], kind: str = "ratio") -> str:
    """Format a number for display.

    kind: 'ratio' -> '1.2x', 'pct' -> '14.5%', 'money' -> '1.2T/3.4B/5.6M IDR'.
    None / non-numeric -> '—'.
    """
    if value is None:
        return "—"
    try:
        v = float(value)
    except Exception:
        return "—"
    if v != v:  # NaN
        return "—"
    if kind == "ratio":
        return f"{v:.2f}x"
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "money":
        a = abs(v)
        sign = "-" if v < 0 else ""
        if a >= 1e12:
            return f"{sign}{a / 1e12:.2f}T"
        if a >= 1e9:
            return f"{sign}{a / 1e9:.2f}B"
        if a >= 1e6:
            return f"{sign}{a / 1e6:.2f}M"
        if a >= 1e3:
            return f"{sign}{a / 1e3:.2f}K"
        return f"{sign}{a:.0f}"
    return str(v)


def fund_score(fin: Optional[Dict]) -> float:
    """0–100 fundamental score from verdict tally over benchmarked metrics.

    +1 weight per '+', -1 per '!', 0 per '=' or missing. Normalized to 0–100
    with 50 = neutral. Returns 50.0 when fin is empty.
    """
    if not fin:
        return 50.0
    metrics = list(BENCHMARK.keys())
    score = 0
    counted = 0
    for m in metrics:
        v = verdict(m, fin.get(m))
        if v == "+":
            score += 1
            counted += 1
        elif v == "!":
            score -= 1
            counted += 1
        elif v == "=":
            counted += 1
    if counted == 0:
        return 50.0
    # map [-counted, +counted] -> [0, 100]
    return round((score / counted + 1.0) / 2.0 * 100.0, 1)


def grade(tech: float, fund: float) -> str:
    """Letter grade A/B/C/D from combined tech + fundamental score."""
    try:
        combined = (float(tech) + float(fund)) / 2.0
    except Exception:
        combined = float(tech or 0.0)
    if combined >= 75:
        return "A"
    if combined >= 60:
        return "B"
    if combined >= 45:
        return "C"
    return "D"


# Tiny self-test of verdict directions (executed only when run directly).
if __name__ == "__main__":
    assert verdict("per", 10) == "+", "PER below bench should be +"
    assert verdict("per", 20) == "!", "PER above bench should be !"
    assert verdict("per", 14.5) == "=", "PER in-line should be ="
    assert verdict("roe", 20) == "+", "ROE above bench should be +"
    assert verdict("roe", 6) == "!", "ROE below bench should be !"
    assert verdict("pbv", None) == "", "None -> ''"
    print("fundamentals self-test OK")
