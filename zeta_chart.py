#!/opt/hermes/.venv/bin/python
"""MAI IDX — chart PNG generator.
Creates dark technical chart: price + MA5/20/50/100/200, volume, RSI, MACD/foreign, PE Band, PBV Band.
"""
import os, sys, math, datetime
sys.path.insert(0, __import__("os").environ.get("ZETA_ROOT", "/opt/data"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

OUTDIR = os.environ.get("ZETA_CHART_DIR", os.environ.get("ZETA_ROOT", "/opt/data") + "/mai_charts")
os.makedirs(OUTDIR, exist_ok=True)


def _sma(vals, n):
    out = []
    for i in range(len(vals)):
        if i + 1 < n:
            out.append(None)
        else:
            out.append(sum(vals[i+1-n:i+1]) / n)
    return out


def _ema_series(vals, n):
    if not vals:
        return []
    k = 2 / (n + 1)
    e = vals[0]
    out = []
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _rsi_series(closes, n=14):
    out = [None] * len(closes)
    if len(closes) < n + 1:
        return out
    for i in range(n, len(closes)):
        gains = losses = 0.0
        for j in range(i - n + 1, i + 1):
            d = closes[j] - closes[j - 1]
            gains += max(d, 0); losses += max(-d, 0)
        ag = gains / n; al = losses / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _fmt_idr(x, _pos=None):
    try:
        x = float(x)
    except Exception:
        return str(x)
    if abs(x) >= 1e12: return f"{x/1e12:.1f}T"
    if abs(x) >= 1e9:  return f"{x/1e9:.1f}B"
    if abs(x) >= 1e6:  return f"{x/1e6:.1f}M"
    return f"{x:.0f}"


def _band_stats(series):
    """Returns (mean, std) of non-None values in series."""
    vals = [v for v in series if v is not None]
    if not vals:
        return None, None
    mean = sum(vals) / len(vals)
    std = math.sqrt(sum((v - mean)**2 for v in vals) / len(vals))
    return mean, std


def _fibonacci_levels(highs, lows, lookback=120):
    """Compute Fibonacci retracement levels from recent swing high/low."""
    recent_h = highs[-lookback:]
    recent_l = lows[-lookback:]
    swing_high = max(recent_h)
    swing_low  = min(recent_l)
    diff = swing_high - swing_low
    if diff <= 0:
        return None
    levels = {}
    for r in [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]:
        levels[r] = swing_low + diff * (1 - r)  # retracement from top
    return {"levels": levels, "high": swing_high, "low": swing_low}


def make_chart(symbol, data, features=None, signal=None, outdir=OUTDIR, fin=None):
    rows = data.get("ohlcv") or []
    if len(rows) < 20:
        raise ValueError(f"not enough rows for chart: {len(rows)}")
    # Keep 240 bars so MA100/MA200 are populated; chart remains readable at 14in wide.
    rows = rows[-240:]
    dates = [r.get("date", str(i)) for i, r in enumerate(rows)]
    x = list(range(len(rows)))
    closes  = [float(r["close"]) for r in rows]
    highs   = [float(r.get("high") or r["close"]) for r in rows]
    lows    = [float(r.get("low")  or r["close"]) for r in rows]
    vols    = [float(r.get("volume") or 0) for r in rows]
    ma5,  ma20  = _sma(closes, 5),  _sma(closes, 20)
    ma50, ma100 = _sma(closes, 50), _sma(closes, 100)
    ma200       = _sma(closes, 200)
    rsi         = _rsi_series(closes, 14)
    ema12, ema26 = _ema_series(closes, 12), _ema_series(closes, 26)
    macd  = [a - b for a, b in zip(ema12, ema26)]
    macds = _ema_series(macd, 9)
    hist  = [a - b for a, b in zip(macd, macds)]
    foreign = [r.get("net_foreign") for r in rows]

    # ── PE Band + PBV Band series (computed from Stockbit ratios + OHLCV) ───
    rat = (fin or {}).get("ratios", {})
    eps_ttm = rat.get("eps_ttm")     # IDR per share
    bvps    = rat.get("bvps")        # IDR per share (book value per share)
    pe_series  = [c / eps_ttm if eps_ttm and eps_ttm > 0 else None for c in closes]
    pbv_series = [c / bvps    if bvps    and bvps    > 0 else None for c in closes]
    pe_mean,  pe_std  = _band_stats(pe_series)
    pbv_mean, pbv_std = _band_stats(pbv_series)
    show_pe_band  = pe_mean  is not None and pe_std  is not None
    show_pbv_band = pbv_mean is not None and pbv_std is not None
    has_valband = show_pe_band or show_pbv_band

    # ── detect MA crossovers ─────────────────────────────────────────────────
    def _crossovers(fast, slow):
        bull, bear = [], []
        for i in range(1, len(fast)):
            f0, f1 = fast[i-1], fast[i]
            s0, s1 = slow[i-1], slow[i]
            if None in (f0, f1, s0, s1):
                continue
            if f0 <= s0 and f1 > s1:
                bull.append(i)
            elif f0 >= s0 and f1 < s1:
                bear.append(i)
        return bull, bear

    macd_bull, macd_bear = _crossovers(macd, macds)

    # ── resistance/support levels for reference (no break markers drawn) ─────
    res20  = features.get("high_20d") if features else max(highs[-20:])
    sup20  = features.get("low_20d")  if features else min(lows[-20:])
    sig_res   = (signal or {}).get("resistance") or res20
    sig_sup   = (signal or {}).get("support")    or sup20

    # ── layout ───────────────────────────────────────────────────────────────
    has_fin  = bool(fin)
    # panels: price | vol | RSI | MACD | [PE+PBV band] | [fund table]
    panels = 4
    heights = [3.6, 1.0, 1.0, 1.0]
    if has_valband:
        panels += 1; heights.append(1.2)
    if has_fin:
        panels += 1; heights.append(1.2)

    plt.style.use("dark_background")
    fig_h = 9 + (1.5 if has_valband else 0) + (1.5 if has_fin else 0)
    fig = plt.figure(figsize=(14, fig_h), dpi=150)
    gs  = fig.add_gridspec(panels, 1, height_ratios=heights, hspace=0.10)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    ax4 = fig.add_subplot(gs[3], sharex=ax1)
    panel_idx = 4
    ax_band = fig.add_subplot(gs[panel_idx], sharex=ax1) if has_valband else None
    if has_valband: panel_idx += 1
    ax5 = fig.add_subplot(gs[panel_idx]) if has_fin else None

    # ── panel 1: price + MA + breaks ─────────────────────────────────────────
    ax1.plot(x, closes, color="#f8fafc", linewidth=2.2, label="Close")
    ax1.plot(x, ma5,   color="#38bdf8", linewidth=1.2, label="MA5")
    ax1.plot(x, ma20,  color="#facc15", linewidth=1.2, label="MA20")
    ax1.plot(x, ma50,  color="#fb7185", linewidth=1.2, label="MA50")
    ax1.plot(x, ma100, color="#c084fc", linewidth=1.0, label="MA100")
    ax1.plot(x, ma200, color="#94a3b8", linewidth=1.0, label="MA200")
    ax1.fill_between(x, lows, highs, color="#64748b", alpha=0.12)

    # resistance/support dotted lines
    if sig_res: ax1.axhline(sig_res, color="#22c55e", alpha=0.35, linestyle="--", linewidth=1)
    if sig_sup: ax1.axhline(sig_sup, color="#ef4444", alpha=0.35, linestyle="--", linewidth=1)

    # ── Fibonacci retracement lines ─────────────────────────────────────────
    _FIB_COLORS = {
        0.0:   ("#f59e0b", 0.90),  # swing low
        0.236: ("#84cc16", 0.75),
        0.382: ("#22d3ee", 0.80),
        0.5:   ("#e879f9", 0.85),  # strongest level
        0.618: ("#f97316", 0.85),  # golden ratio
        0.786: ("#60a5fa", 0.75),
        1.0:   ("#f59e0b", 0.90),  # swing high
    }
    fib_data = _fibonacci_levels(highs, lows, lookback=min(120, len(highs)))
    if fib_data:
        for ratio, price_lvl in fib_data["levels"].items():
            col, alpha = _FIB_COLORS.get(ratio, ("#ffffff", 0.5))
            ax1.axhline(price_lvl, color=col, alpha=alpha,
                        linestyle=":", linewidth=0.9, zorder=2)
            ax1.text(len(x) - 1, price_lvl,
                     f" Fib {ratio:.3f}  {price_lvl:,.0f}",
                     color=col, fontsize=6.5, va="center", ha="right",
                     alpha=alpha, zorder=9)

    # ── break-up / break-down X markers ──────────────────────────────────────
    break_up_idxs   = []  # close crossed above resistance → green X
    break_down_idxs = []  # close dropped below support    → red X
    for i in range(1, len(closes)):
        prev, curr = closes[i-1], closes[i]
        if sig_res and prev <= sig_res and curr > sig_res:
            break_up_idxs.append(i)
        if sig_sup and prev >= sig_sup and curr < sig_sup:
            break_down_idxs.append(i)

    if break_up_idxs:
        bux = break_up_idxs
        buy = [closes[i] for i in bux]
        ax1.scatter(bux, buy, marker="x", color="#00ff88", s=220, zorder=8,
                    linewidths=3.5, label="Break up")
        for xi, yi in zip(bux[-3:], buy[-3:]):
            ax1.annotate("X", (xi, yi), textcoords="offset points", xytext=(0, 10),
                         ha="center", color="#00ff88", fontsize=11, fontweight="bold")

    if break_down_idxs:
        bdx = break_down_idxs
        bdy = [closes[i] for i in bdx]
        ax1.scatter(bdx, bdy, marker="x", color="#ff3333", s=220, zorder=8,
                    linewidths=3.5, label="Break dn")
        for xi, yi in zip(bdx[-3:], bdy[-3:]):
            ax1.annotate("X", (xi, yi), textcoords="offset points", xytext=(0, -18),
                         ha="center", color="#ff3333", fontsize=11, fontweight="bold")

    # ── realtime current price: no yellow line/label drawn (removed per user) ─
    rt_price = (features or {}).get("realtime_price") or closes[-1]
    price_src = (features or {}).get("realtime_ts") or (features or {}).get("price_source", "")

    sig_val  = (signal or {}).get("signal", "")
    conf_val = (signal or {}).get("confidence", "")
    r_info   = (signal or {}).get("_rank", {})
    score_txt = (f"Score {r_info.get('composite_score', r_info.get('total'))}/100 "
                 f"{r_info.get('grade')} T:{r_info.get('technical_score')} "
                 f"F:{r_info.get('fundamental_score')}") if r_info else ""
    # ASCII-only trend tag to avoid emoji/font glyph-missing warnings.
    _trend_tag = {"UPTREND": "Trend: NAIK", "DOWNTREND": "Trend: TURUN", "SIDEWAYS": "Trend: SIDEWAYS"}
    trend_regime = (features or {}).get("trend_regime", "")
    trend_lbl    = f" | {_trend_tag.get(trend_regime, trend_regime)}" if trend_regime else ""
    title = (f"{symbol} - {sig_val} {conf_val}% {score_txt}{trend_lbl} | "
             f"Price {rt_price:.0f} [{price_src}] | "
             f"RSI {features.get('rsi14') if features else '-'} | "
             f"Foreign {features.get('foreign_trend') if features else '-'}")
    ax1.set_title(title, loc="left", fontsize=13, fontweight="bold")
    ax1.legend(loc="upper left", ncol=6, fontsize=7.5, frameon=False)
    ax1.grid(alpha=0.15)

    # ── panel 2: volume (green/red by close>=open, gray if no open) ───────────
    opens = [r.get("open") for r in rows]
    def _vcol(i):
        o = opens[i]
        if o is None:
            return "#94a3b8"
        return "#22c55e" if closes[i] >= float(o) else "#ef4444"
    vcols = [_vcol(i) for i in range(len(closes))]
    ax2.bar(x, vols, color=vcols, alpha=0.65, width=0.8)
    ax2.yaxis.set_major_formatter(FuncFormatter(_fmt_idr))
    ax2.set_ylabel("Vol", fontsize=8)
    ax2.grid(alpha=0.12)

    # ── panel 3: RSI ─────────────────────────────────────────────────────────
    ax3.plot(x, rsi, color="#a78bfa", linewidth=1.3)
    ax3.axhline(70, color="#ef4444", alpha=0.45, linestyle="--")
    ax3.axhline(30, color="#22c55e", alpha=0.45, linestyle="--")
    ax3.set_ylim(0, 100)
    ax3.set_ylabel("RSI", fontsize=8)
    ax3.grid(alpha=0.12)

    # ── panel 4: MACD + foreign ───────────────────────────────────────────────
    ax4.bar(x, hist, color=["#22c55e" if h >= 0 else "#ef4444" for h in hist],
            alpha=0.45, width=0.8, label="MACD hist")
    ax4.plot(x, macd,  color="#38bdf8", linewidth=1, label="MACD")
    ax4.plot(x, macds, color="#f97316", linewidth=1, label="Signal")
    if macd_bull:
        ax4.scatter(macd_bull, [macd[i] for i in macd_bull],
                    marker="x", color="#22c55e", s=90, linewidths=2.2, zorder=5, label="MACDxSignal up")
    if macd_bear:
        ax4.scatter(macd_bear, [macd[i] for i in macd_bear],
                    marker="x", color="#ef4444", s=90, linewidths=2.2, zorder=5, label="MACDxSignal dn")
    ax4.legend(loc="upper left", ncol=4, fontsize=7, frameon=False)
    ax4.set_ylabel("MACD", fontsize=8)
    ax4.grid(alpha=0.12)
    if any(v is not None for v in foreign):
        ax4b = ax4.twinx()
        fx = [i for i, v in enumerate(foreign) if v is not None]
        fv = [float(v) for v in foreign if v is not None]
        ax4b.bar(fx, fv, color=["#22c55e" if v >= 0 else "#ef4444" for v in fv],
                 alpha=0.28, width=0.55, label="Net foreign")
        ax4b.yaxis.set_major_formatter(FuncFormatter(_fmt_idr))
        ax4b.set_ylabel("Foreign", fontsize=8)

    # ── panel 5: PE Band + PBV Band ──────────────────────────────────────────
    if has_valband and ax_band is not None:
        ax_band.set_facecolor("#020617")
        # PE Band (left y-axis)
        if show_pe_band:
            pe_vals = [v for v in pe_series if v is not None]
            pe_xs   = [i for i, v in enumerate(pe_series) if v is not None]
            pe_y = [pe_series[i] for i in pe_xs]
            ax_band.plot(pe_xs, pe_y,
                         color="#00e5ff", linewidth=2.8, linestyle="-", zorder=8,
                         label=f"PE (now {pe_series[-1]:.1f}x)")
            if pe_y:
                pad = max((max(pe_y) - min(pe_y)) * 0.18, 0.8)
                ax_band.set_ylim(min(pe_y) - pad, max(pe_y) + pad)
            # band lines: mean, ±1σ, ±2σ
            for mult, alpha, ls, lw in [(0, 0.95, "-", 1.6), (1, 0.75, "--", 1.2), (-1, 0.75, "--", 1.2),
                                        (2, 0.50, ":", 1.0), (-2, 0.50, ":", 1.0)]:
                val = pe_mean + mult * pe_std
                ax_band.axhline(val, color="#00e5ff", alpha=alpha, linestyle=ls, linewidth=lw, zorder=6)
                if mult >= 0:
                    ax_band.text(len(x) - 1, val, f"PE {val:.1f}x",
                                 color="#00e5ff", fontsize=7, va="center", ha="right", alpha=alpha, zorder=9)
            ax_band.set_ylabel("PE", fontsize=8, color="#00e5ff")
            ax_band.tick_params(axis="y", labelcolor="#00e5ff", labelsize=7)

        # PBV Band (right y-axis)
        if show_pbv_band:
            pbv_xs = [i for i, v in enumerate(pbv_series) if v is not None]
            ax_band_r = ax_band.twinx()
            ax_band_r.plot(pbv_xs, [pbv_series[i] for i in pbv_xs],
                           color="#facc15", linewidth=1.4, linestyle="--", alpha=0.85, zorder=4,
                           label=f"PBV (now {pbv_series[-1]:.2f}x)")
            for mult, alpha, ls in [(0, 0.55, "-"), (1, 0.38, "--"), (-1, 0.38, "--"),
                                     (2, 0.25, ":"), (-2, 0.25, ":")]:
                val = pbv_mean + mult * pbv_std
                ax_band_r.axhline(val, color="#facc15", alpha=alpha, linestyle=ls, linewidth=0.8, zorder=3)
                if mult >= 0:
                    ax_band_r.text(0, val, f"PBV {val:.2f}x",
                                   color="#facc15", fontsize=6.5, va="center", ha="left", alpha=alpha)
            ax_band_r.set_ylabel("PBV", fontsize=8, color="#facc15")
            ax_band_r.tick_params(axis="y", labelcolor="#facc15", labelsize=7)

        # combined legend
        lines1, labs1 = ax_band.get_legend_handles_labels()
        if show_pbv_band:
            lines2, labs2 = ax_band_r.get_legend_handles_labels()
            ax_band.legend(lines1 + lines2, labs1 + labs2,
                           loc="upper left", ncol=2, fontsize=7, frameon=False)
        else:
            ax_band.legend(lines1, labs1, loc="upper left", fontsize=7, frameon=False)
        ax_band.set_title("PE Band & PBV Band (computed dari EPS TTM & BVPS Stockbit)",
                          loc="left", fontsize=7.5, color="#64748b", pad=2)
        ax_band.grid(alpha=0.10)

    # ── x-ticks: show on bottom-most sharex panel ────────────────────────────
    last_sharex = ax_band if has_valband else ax4
    ticks = x[::max(1, len(x)//8)]
    last_sharex.set_xticks(ticks)
    last_sharex.set_xticklabels([dates[i][5:] for i in ticks], rotation=0, fontsize=8)
    hide_axes = [ax1, ax2, ax3, ax4]
    if has_valband and ax_band is not None and ax_band is not last_sharex:
        hide_axes.append(ax_band)
    for ax in hide_axes:
        plt.setp(ax.get_xticklabels(), visible=False)
    # suppress x-tick labels on last_sharex if fund panel follows (ax5 doesn't share x)
    # keep them visible so user sees dates below band panel

    # ── panel 6: Fundamental table ────────────────────────────────────────────
    if has_fin and ax5 is not None:
        ax5.set_facecolor("#020617")
        ax5.axis("off")
        rat2 = fin.get("ratios", {}); pnl_d = fin.get("pnl", {})
        bs   = fin.get("bs", {});    cf    = fin.get("cf", {})
        def _v2(val): return str(val) if val is not None else "n/a"
        def _pct2(val): return f"{val:.1f}%" if val is not None else "n/a"
        def _bt2(val):
            if val is None: return "n/a"
            sign = "-" if val < 0 else ""; val = abs(val)
            return f"{sign}{val/1000:.1f}T" if val >= 1000 else f"{sign}{val:.0f}B"

        # Industry benchmark for compare
        try:
            import zeta_industry as zi
            ind = zi.get(symbol)
            ind_label = ind.get("label", "IDX")
        except Exception:
            ind = {}
            ind_label = "IDX"

        def _cmp(metric, val, suffix="x"):
            """Format value + vs-industry verdict."""
            if val is None:
                return "n/a"
            fmt = f"{val:.1f}{suffix}"
            iv = ind.get(metric)
            if iv is None:
                return fmt
            try:
                import zeta_industry as zi
                vd = zi.verdict(metric, val, iv)
                arrow = "[+]" if "atas" in vd or "murah" in vd else ("[!]" if "bawah" in vd or "mahal" in vd else "[=]")
                return f"{fmt} {arrow} vs {iv:.1f}{suffix}"
            except Exception:
                return fmt

        rows_tab = [
            ["Valuation",
             f"PER {_cmp('per_ttm', rat2.get('per_ttm'))}",
             f"PBV {_cmp('pbv', rat2.get('pbv'))}",
             f"EV/EBITDA {_v2(rat2.get('ev_ebitda'))}x",
             f"DivY {_pct2(rat2.get('dividend_yield_pct'))}"],
            ["Profitability",
             f"ROE {_cmp('roe_pct', rat2.get('roe_pct'), '%')}",
             f"ROA {_cmp('roa_pct', rat2.get('roa_pct'), '%')}",
             f"NM {_cmp('net_margin_pct', rat2.get('net_margin_pct'), '%')}",
             f"EPS {_v2(rat2.get('eps_ttm'))}"],
            ["P&L (TTM)", f"Rev {_bt2(pnl_d.get('revenue_ttm_b'))}", f"Rev YoY {_pct2(pnl_d.get('revenue_yoy_pct'))}",
             f"EBITDA {_bt2(pnl_d.get('ebitda_ttm_b'))}", f"NI {_bt2(pnl_d.get('net_income_ttm_b'))} ({_pct2(pnl_d.get('net_income_yoy_pct'))} YoY)"],
            ["Balance Sheet", f"Assets {_bt2(bs.get('total_assets_q_b'))}", f"Equity {_bt2(bs.get('total_equity_q_b'))}",
             f"Cash {_bt2(bs.get('cash_q_b'))}", f"DER {_v2(rat2.get('der'))}"],
            ["Cash Flow", f"OCF {_bt2(cf.get('ocf_ttm_b'))}", f"Capex {_bt2(cf.get('capex_ttm_b'))}",
             f"FCF {_bt2(cf.get('fcf_ttm_b'))}", f"vs industri: {ind_label}"],
        ]
        cell_text = [[r[0], r[1], r[2], r[3], r[4]] for r in rows_tab]
        tbl = ax5.table(cellText=cell_text, cellLoc="left", loc="center", bbox=[0, 0, 1, 1])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8.0)
        for (row_i, col_i), cell in tbl.get_celld().items():
            cell.set_edgecolor("#334155")
            if col_i == 0:
                cell.set_facecolor("#0f172a"); cell.set_text_props(color="#94a3b8", fontweight="bold")
            else:
                cell.set_facecolor("#1e293b"); cell.set_text_props(color="#e2e8f0")
        ax5.set_title(f"Fundamental  ([+] di atas/murah vs industri  [!] mahal/di bawah  [=] inline — benchmark: {ind_label})",
                      loc="left", fontsize=8, color="#64748b", pad=2)
        ax5.axis("off")

    # ── global style ──────────────────────────────────────────────────────────
    fig.patch.set_facecolor("#020617")
    all_axes = [ax1, ax2, ax3, ax4]
    if ax_band: all_axes.append(ax_band)
    if ax5:     all_axes.append(ax5)
    for ax in all_axes:
        ax.set_facecolor("#020617")
        for spine in ax.spines.values(): spine.set_alpha(0.2)

    path = os.path.join(outdir, f"{symbol}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


if __name__ == "__main__":
    import importlib, json
    import zeta_stockbit_data as zd, zeta_features as zf, zeta_financials as zfin
    sym = sys.argv[1] if len(sys.argv) > 1 else "BBRI"
    d   = zd.fetch_symbol(sym)
    f   = zf.build_features(d)
    fin = None
    try: fin = zfin.fetch_financials(sym)
    except: pass
    try:
        import zeta_rank as zr
        rank = zr.score(f, fin)
        sig = {"signal": rank.get("rank_label", "HOLD"), "confidence": rank.get("pct", 0), "_rank": rank}
    except Exception:
        sig = {"signal": "HOLD", "confidence": 0}
    print(make_chart(sym, d, f, sig, fin=fin))
