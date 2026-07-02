#!/usr/bin/env python3
"""zeta_compare.py TICKER1,TICKER2[,TICKER3...]
Side-by-side comparison table for IDX stocks using Zeta engine.
"""
import sys, os, concurrent.futures
sys.path.insert(0, os.environ.get("ZETA_ROOT", "/opt/data"))

import zeta_stockbit_data as zd
import zeta_financials as zf
import zeta_features as zft
import zeta_rank as zr
import zeta_llm as llm

# ── helpers ──────────────────────────────────────────────────────────────────

def _n(v, suffix="", decimals=1):
    if v is None: return "n/a"
    try:
        f = float(v)
        return f"{f:,.{decimals}f}{suffix}"
    except Exception:
        return str(v)

def _pct(v):
    return _n(v, "%")

def _x(v):
    return _n(v, "x")

def _flag(v, good_if_high=True, threshold=0):
    """Return 🟢/🔴/⚪ based on sign."""
    if v is None: return "⚪"
    try:
        f = float(v)
        if good_if_high:
            return "🟢" if f > threshold else ("🔴" if f < threshold else "⚪")
        else:
            return "🟢" if f < threshold else ("🔴" if f > threshold else "⚪")
    except Exception:
        return "⚪"

SIGNAL_EMOJI = {
    "BUY": "🟢", "BUY KUAT": "🟢", "BUY LEMAH": "🟡",
    "HOLD": "🟡", "HOLD NETRAL": "🟡", "HOLD-SELL": "🟠",
    "SELL": "🔴", "SELL KUAT": "🔴",
}

TREND_SHORT = {"UPTREND": "📈 NAIK", "DOWNTREND": "📉 TURUN", "SIDEWAYS": "➡️ FLAT"}

# ── per-symbol fetch ──────────────────────────────────────────────────────────

def fetch_one(sym):
    sym = sym.upper().strip()
    try:
        data = zd.fetch_symbol(sym)
        feats = zft.build_features(data)
        fin = zf.fetch_financials(sym)
        rat = fin.get('ratios', {}) if isinstance(fin, dict) else {}
        sig = zr.score(feats, fin)
        return sym, feats, rat, sig, fin, None
    except Exception as e:
        import traceback; traceback.print_exc()
        return sym, {}, {}, {}, {}, str(e)

# ── comparison table ──────────────────────────────────────────────────────────

def _cell(val, flag=""):
    return f"{flag}{val}" if flag else val

def compare(symbols):
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch_one, s): s for s in symbols}
        for fut in concurrent.futures.as_completed(futs):
            sym, feats, rat, sig, fin, err = fut.result()
            results[sym] = (feats, rat, sig, fin, err)

    # Order output as input
    syms = [s.upper().strip() for s in symbols]

    # ── rows ──
    rows = []

    def hdr(label):
        rows.append(("__HDR__", label))

    def row(label, vals):
        rows.append((label, vals))

    # Signal / Score
    hdr("📊 SIGNAL")
    row("Signal", [
        f"{SIGNAL_EMOJI.get(results[s][2].get('rank_label','?'), '⚪')} {results[s][2].get('rank_label','n/a')}"
        if not results[s][4] else f"❌ {results[s][4][:20]}"
        for s in syms
    ])
    row("Score", [_n(results[s][2].get("composite_score"), "/100", 0) for s in syms])
    row("Grade", [results[s][2].get("grade", "n/a") for s in syms])

    # Price / Trend
    hdr("💰 HARGA & TREND")
    row("Harga", [
        f"Rp{results[s][0].get('realtime_price') or results[s][0].get('close','n/a'):,.0f}"
        if results[s][0].get('realtime_price') or results[s][0].get('close')
        else "n/a"
        for s in syms
    ])
    row("Trend D", [TREND_SHORT.get(results[s][0].get("trend_regime",""), "n/a") for s in syms])
    row("RSI", [_n(results[s][0].get("rsi14"), "", 1) for s in syms])
    row("R/R", [_n(results[s][0].get("risk_reward_tp1"), "x", 1) for s in syms])

    # Foreign flow
    hdr("🏦 FLOW")
    row("Foreign 5D", [
        (lambda v: f"{'🟢' if v and v>0 else '🔴' if v and v<0 else '⚪'} Rp{abs(v)/1e9:.1f}B {'masuk' if v>0 else 'keluar'}"
         if v is not None else "n/a")(results[s][0].get("net_foreign_5d"))
        for s in syms
    ])
    row("Smart $", [results[s][0].get("broker_bias", "n/a") for s in syms])

    # Valuation
    hdr("📐 VALUASI")
    row("PER", [
        _cell(_x(results[s][1].get("per_ttm")), _flag(results[s][1].get("per_ttm"), good_if_high=False, threshold=20))
        for s in syms
    ])
    row("PBV", [
        _cell(_x(results[s][1].get("pbv")), _flag(results[s][1].get("pbv"), good_if_high=False, threshold=3))
        for s in syms
    ])
    row("EV/EBITDA", [_x(results[s][1].get("ev_ebitda")) for s in syms])
    row("Div Yield", [
        _cell(_pct(results[s][1].get("dividend_yield_pct")),
              "🟢 " if results[s][1].get("dividend_yield_pct") and float(results[s][1].get("dividend_yield_pct") or 0) > 2 else "")
        for s in syms
    ])

    # Profitability
    hdr("📈 PROFITABILITAS")
    row("ROE", [_cell(_pct(results[s][1].get("roe_pct")), _flag(results[s][1].get("roe_pct"), threshold=10)) for s in syms])
    row("ROA", [_cell(_pct(results[s][1].get("roa_pct")), _flag(results[s][1].get("roa_pct"), threshold=5)) for s in syms])
    row("Net Margin", [_cell(_pct(results[s][1].get("net_margin_pct")), _flag(results[s][1].get("net_margin_pct"), threshold=5)) for s in syms])

    # P&L — from fin['pnl']
    hdr("💵 P&L (TTM)")
    row("Rev YoY", [
        _cell(_pct(results[s][3].get("pnl", {}).get("revenue_yoy_pct") if isinstance(results[s][3], dict) else None),
              _flag(results[s][3].get("pnl", {}).get("revenue_yoy_pct") if isinstance(results[s][3], dict) else None, threshold=0))
        for s in syms
    ])
    row("NI YoY", [
        _cell(_pct(results[s][3].get("pnl", {}).get("net_income_yoy_pct") if isinstance(results[s][3], dict) else None),
              _flag(results[s][3].get("pnl", {}).get("net_income_yoy_pct") if isinstance(results[s][3], dict) else None, threshold=0))
        for s in syms
    ])
    row("FCF", [
        (lambda v: f"{'🟢' if v and v>0 else '🔴'} Rp{v:.0f}B" if v else "n/a")(
            results[s][3].get("cf", {}).get("fcf_b") if isinstance(results[s][3], dict) else None
        )
        for s in syms
    ])

    # ── render ──
    n = len(syms)
    COL = 14  # min col width

    def pad(s, w):
        # strip emoji for width calc is tricky; just pad by chars
        return str(s).ljust(w)

    label_w = 12
    col_w = max(COL, max(len(s) for s in syms) + 2)

    sep = "─" * (label_w + 2 + (col_w + 3) * n)

    header_line = " " * (label_w + 2) + " | ".join(s.center(col_w) for s in syms)
    lines = [
        f"📊 *KOMPARASI: {' vs '.join(syms)}*",
        f"`{sep}`",
        f"`{header_line}`",
        f"`{sep}`",
    ]

    for label, vals in rows:
        if label == "__HDR__":
            lines.append(f"\n*{vals}*")
        else:
            cells = " | ".join(str(v).center(col_w) for v in vals)
            lines.append(f"`{label.ljust(label_w)}  {cells}`")

    lines.append(f"\n`{sep}`")

    # ── LLM ranking ──
    try:
        prompt_data = "\n".join(
            f"{s}: score={results[s][2].get('composite_score','?')}, signal={results[s][2].get('rank_label','?')}, "
            f"ROE={results[s][1].get('roe_pct','?')}%, DivY={results[s][1].get('dividend_yield_pct','?')}%, "
            f"PER={results[s][1].get('per_ttm','?')}x, trend={results[s][0].get('trend_regime','?')}, "
            f"foreign_net={results[s][0].get('net_foreign_5d','?')}, rr={results[s][0].get('risk_reward_tp1','?')}"
            for s in syms
        )
        resp = llm.chat([
            {"role": "system", "content": "Kamu analis saham IDX. Jawab singkat dalam bahasa Indonesia."},
            {"role": "user", "content":
                f"Berikan ranking 1 kalimat untuk saham-saham ini dan 1 kalimat alasan pilihan terbaik:\n{prompt_data}"}
        ], model="cc/claude-sonnet-4-6", max_tokens=150)
        lines.append(f"\n🏆 *RANKING:* {resp.strip()}")
    except Exception as e:
        lines.append(f"\n🏆 *RANKING:* (llm skip: {e})")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: zeta_compare.py BBCA,BBRI,BMRI")
        sys.exit(1)
    tickers = sys.argv[1].split(",")
    if len(tickers) < 2:
        print("Minimal 2 saham untuk dibandingkan.")
        sys.exit(1)
    print(compare(tickers))
