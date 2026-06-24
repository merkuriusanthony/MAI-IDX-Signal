"""Chart generation using matplotlib.

5-panel deep-analysis chart with optional fundamental band + table.
generate_chart stays total: fin=None / foreign_df=None produces a valid chart
(panels 1-4 always; panel 5 shows "Fundamental N/A"; table omitted). Never
raises — returns "" on total failure.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Optional

import pandas as pd

from app.analytics.fundamentals import fmt, fund_score, grade, verdict

logger = logging.getLogger(__name__)

# Panel-1 MA palette (task spec — differs from legacy colors).
_C_CLOSE = "#ffffff"
_C_MA5 = "#00d2ff"
_C_MA20 = "#ffd700"
_C_MA50 = "#ff6b6b"
_C_MA100 = "#a855f7"
_C_MA200 = "#9ca3af"
_BG = "#0d1117"
_GRID = "#30363d"


def _chart_dir() -> str:
    from app.config import settings
    d = settings.CHART_DIR
    os.makedirs(d, exist_ok=True)
    return d


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except Exception:
        return None


def generate_chart(
    symbol: str,
    df: pd.DataFrame,
    signal: Dict,
    fin: Optional[Dict] = None,
    foreign_df: Optional[pd.DataFrame] = None,
) -> str:
    """Render a 5-panel chart + fundamental table, save PNG, return its path.

    Backward compatible: fin/foreign_df default None -> valid chart, no crash.
    Returns empty string on failure — never raises.
    """
    if df is None or df.empty:
        return ""

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec
    except ImportError:
        logger.warning("matplotlib not available — skipping chart")
        return ""

    chart_dir = _chart_dir()
    out_path = os.path.join(chart_dir, f"{symbol.upper()}.png")
    fin = fin or {}
    snap = signal.get("snapshot", {}) if isinstance(signal, dict) else {}

    try:
        plot_df = df.tail(120).copy()
        close = plot_df["close"]
        idx = plot_df.index

        ma5 = close.rolling(5, min_periods=1).mean()
        ma20 = close.rolling(20, min_periods=1).mean()
        ma50 = close.rolling(50, min_periods=1).mean()
        ma100 = close.rolling(100, min_periods=1).mean()
        ma200 = close.rolling(200, min_periods=1).mean()

        has_table = bool(fin)
        # 6 rows: 5 panels + (optional) table band.
        if has_table:
            ratios = [40, 10, 13, 17, 20, 16]
            nrows = 6
        else:
            ratios = [40, 10, 13, 17, 20]
            nrows = 5
        fig = plt.figure(figsize=(13, 16 if has_table else 14))
        fig.patch.set_facecolor(_BG)
        gs = GridSpec(nrows, 1, height_ratios=ratios, hspace=0.28)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax3 = fig.add_subplot(gs[2], sharex=ax1)
        ax4 = fig.add_subplot(gs[3], sharex=ax1)
        ax5 = fig.add_subplot(gs[4], sharex=ax1)
        ax_table = fig.add_subplot(gs[5]) if has_table else None

        for ax in (ax1, ax2, ax3, ax4, ax5):
            ax.set_facecolor(_BG)
            ax.tick_params(colors="white", labelsize=8)
            ax.spines[:].set_color(_GRID)
            ax.grid(True, alpha=0.15, color=_GRID)

        # --- Panel 1: Price + MA + fib + cross/break + levels -------------
        try:
            _panel_price(ax1, idx, close, ma5, ma20, ma50, ma100, ma200,
                         signal, snap)
        except Exception as exc:
            logger.debug("panel1 failed for %s: %s", symbol, exc)

        # --- Panel 2: Volume ----------------------------------------------
        try:
            if "volume" in plot_df.columns:
                colors = ["#3fb950" if c >= o else "#f85149"
                          for c, o in zip(plot_df["close"], plot_df["open"])]
                ax2.bar(idx, plot_df["volume"].values, color=colors, width=0.8, alpha=0.7)
            ax2.set_ylabel("Vol", color="white", fontsize=8)
        except Exception as exc:
            logger.debug("panel2 failed for %s: %s", symbol, exc)

        # --- Panel 3: RSI -------------------------------------------------
        try:
            from app.analytics.indicators import rsi as _rsi
            rsi_s = _rsi(plot_df, 14)
            ax3.plot(idx, rsi_s.values, color="#a371f7", linewidth=1.2, label="RSI")
            ax3.axhline(70, color="#f85149", linestyle="--", linewidth=0.7, alpha=0.7)
            ax3.axhline(30, color="#3fb950", linestyle="--", linewidth=0.7, alpha=0.7)
            ax3.set_ylim(0, 100)
            ax3.set_ylabel("RSI", color="white", fontsize=8)
        except Exception as exc:
            logger.debug("panel3 failed for %s: %s", symbol, exc)

        # --- Panel 4: MACD (+ foreign net twin) ---------------------------
        try:
            _panel_macd(ax4, plot_df, idx, foreign_df)
        except Exception as exc:
            logger.debug("panel4 failed for %s: %s", symbol, exc)

        # --- Panel 5: PE / PBV band ---------------------------------------
        try:
            _panel_bands(ax5, idx, close, fin)
        except Exception as exc:
            logger.debug("panel5 failed for %s: %s", symbol, exc)
            ax5.text(0.5, 0.5, "Fundamental N/A", color="#9ca3af",
                     ha="center", va="center", transform=ax5.transAxes)

        # --- Table band ---------------------------------------------------
        if ax_table is not None:
            try:
                _render_table(ax_table, fin)
            except Exception as exc:
                logger.debug("table failed for %s: %s", symbol, exc)
                ax_table.axis("off")

        # --- Header suptitle ----------------------------------------------
        try:
            fig.suptitle(_header(symbol, signal, snap, fin),
                         color="white", fontsize=12, y=0.995)
        except Exception:
            pass

        fig.savefig(out_path, dpi=90, facecolor=fig.get_facecolor(),
                    bbox_inches="tight")
        logger.debug("chart saved: %s", out_path)
        return out_path
    except Exception as exc:
        logger.warning("chart generation failed for %s: %s", symbol, exc)
        return ""
    finally:
        try:
            import matplotlib.pyplot as plt
            plt.close("all")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Panel helpers
# ---------------------------------------------------------------------------

def _panel_price(ax, idx, close, ma5, ma20, ma50, ma100, ma200, signal, snap):
    ax.plot(idx, close.values, label="Close", color=_C_CLOSE, linewidth=1.4)
    ax.plot(idx, ma5.values, label="MA5", color=_C_MA5, linewidth=0.9, alpha=0.85)
    ax.plot(idx, ma20.values, label="MA20", color=_C_MA20, linewidth=0.9, alpha=0.85)
    ax.plot(idx, ma50.values, label="MA50", color=_C_MA50, linewidth=0.9, alpha=0.85)
    ax.plot(idx, ma100.values, label="MA100", color=_C_MA100, linewidth=0.8, alpha=0.7)
    ax.plot(idx, ma200.values, label="MA200", color=_C_MA200, linewidth=0.9, alpha=0.7)

    # Fib dotted levels
    fib = (snap or {}).get("fib") or {}
    for lvl, price in fib.items():
        p = _num(price)
        if p and p > 0:
            ax.axhline(p, color="#6e7681", linestyle=":", linewidth=0.6, alpha=0.5)

    # MA crossover markers (ma5/ma20)
    try:
        diff = (ma5 - ma20).dropna()
        sign = diff.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        chg = sign.diff()
        for i in chg[chg != 0].index:
            if i not in close.index:
                continue
            up = chg.loc[i] > 0
            ax.scatter([i], [close.loc[i]], marker="^" if up else "v",
                       color="#3fb950" if up else "#f85149", s=55, zorder=5)
    except Exception:
        pass

    # Break markers vs resistance/support
    try:
        sr = (snap or {}).get("support_resistance") or {}
        res = _num(sr.get("resistance"))
        sup = _num(sr.get("support"))
        prev = close.shift(1)
        if res and res > 0:
            cross = close[(close > res) & (prev <= res)]
            for i in cross.index:
                ax.scatter([i], [close.loc[i]], marker="*", color="#3fb950", s=80, zorder=6)
        if sup and sup > 0:
            cross = close[(close < sup) & (prev >= sup)]
            for i in cross.index:
                ax.scatter([i], [close.loc[i]], marker="x", color="#f85149", s=60, zorder=6)
    except Exception:
        pass

    # Entry / TP / SL lines
    for key, color, style in (
        ("entry", "#3fb950", "--"),
        ("tp1", "#58a6ff", ":"),
        ("tp2", "#a371f7", ":"),
        ("stop_loss", "#f85149", "--"),
    ):
        val = _num(signal.get(key))
        if val and val > 0:
            ax.axhline(val, color=color, linestyle=style, linewidth=1.1,
                       label=key.upper().replace("_", " "), alpha=0.9)

    ax.legend(loc="upper left", fontsize=7, facecolor="#161b22",
              labelcolor="white", ncol=2)
    ax.set_ylabel("Price", color="white", fontsize=8)


def _panel_macd(ax, plot_df, idx, foreign_df):
    from app.analytics.indicators import macd as _macd
    m = _macd(plot_df)
    ax.plot(idx, m["macd"].values, color="#58a6ff", linewidth=1.0, label="MACD")
    ax.plot(idx, m["signal"].values, color="#f0c040", linewidth=1.0, label="Signal")
    hist = m["hist"]
    hcolors = ["#3fb950" if v >= 0 else "#f85149" for v in hist.values]
    ax.bar(idx, hist.values, color=hcolors, width=0.8, alpha=0.6)
    ax.set_ylabel("MACD", color="white", fontsize=8)
    ax.legend(loc="upper left", fontsize=7, facecolor="#161b22", labelcolor="white")

    # Foreign net twin axis
    if foreign_df is not None and not foreign_df.empty and "foreign_net" in foreign_df.columns:
        try:
            fdf = foreign_df.copy()
            if "date" in fdf.columns:
                fdf = fdf.set_index(pd.to_datetime(fdf["date"], errors="coerce"))
            fnet = pd.to_numeric(fdf["foreign_net"], errors="coerce")
            fnet = fnet.reindex(idx).fillna(0.0)
            if fnet.abs().sum() > 0:
                axt = ax.twinx()
                axt.bar(idx, fnet.values, color="#26c6da", width=0.5, alpha=0.35)
                axt.set_ylabel("FA net", color="#26c6da", fontsize=7)
                axt.tick_params(colors="#26c6da", labelsize=7)
        except Exception:
            pass


def _panel_bands(ax, idx, close, fin):
    ax.set_ylabel("PE / PBV", color="white", fontsize=8)
    eps = _num(fin.get("eps_ttm")) if fin else None
    bvps = _num(fin.get("bvps")) if fin else None
    plotted = False

    if eps and eps > 0:
        pe = close / eps
        ax.plot(idx, pe.values, color="#22d3ee", linewidth=1.1, label="PE")
        _bands(ax, pe, "#22d3ee")
        ax.text(0.01, 0.92, f"PE {pe.iloc[-1]:.1f}x", color="#22d3ee",
                fontsize=7, transform=ax.transAxes)
        plotted = True

    if bvps and bvps > 0:
        pbv = close / bvps
        axr = ax.twinx()
        axr.plot(idx, pbv.values, color="#f59e0b", linewidth=1.1,
                 linestyle="--", label="PBV")
        _bands(axr, pbv, "#f59e0b")
        axr.tick_params(colors="#f59e0b", labelsize=7)
        axr.text(0.99, 0.92, f"PBV {pbv.iloc[-1]:.2f}x", color="#f59e0b",
                 fontsize=7, ha="right", transform=ax.transAxes)
        plotted = True

    if plotted:
        ax.legend(loc="upper left", fontsize=7, facecolor="#161b22", labelcolor="white")
    else:
        ax.text(0.5, 0.5, "Fundamental N/A", color="#9ca3af",
                ha="center", va="center", transform=ax.transAxes)


def _bands(ax, series, color):
    """Draw mean ±1σ / ±2σ horizontal dashed bands over the plotted window."""
    s = series.dropna()
    if len(s) < 2:
        return
    mu = float(s.mean())
    sigma = float(s.std())
    if sigma <= 0:
        return
    for k, alpha in ((1, 0.35), (2, 0.2)):
        for sgn in (1, -1):
            ax.axhline(mu + sgn * k * sigma, color=color, linestyle=":",
                       linewidth=0.6, alpha=alpha)
    ax.axhline(mu, color=color, linestyle="-", linewidth=0.5, alpha=0.4)


# ---------------------------------------------------------------------------
# Table + header
# ---------------------------------------------------------------------------

_VERDICT_COLOR = {"+": "#3fb950", "!": "#f85149", "=": "#9ca3af", "": "#c9d1d9"}


def _cell(fin, key, kind, bench=False):
    v = fin.get(key)
    txt = fmt(v, kind)
    if bench and v is not None:
        tag = verdict(key, v)
        if tag:
            txt = f"{txt} [{tag}]"
        return txt, _VERDICT_COLOR.get(tag, "#c9d1d9")
    return txt, "#c9d1d9"


def _render_table(ax, fin):
    ax.axis("off")
    rows = [
        ("Valuation", [
            ("PER", "per", "ratio", True), ("PBV", "pbv", "ratio", True),
            ("EV/EBITDA", "ev_ebitda", "ratio", False),
            ("DivY", "div_yield", "pct", False), ("EPS", "eps_ttm", "money", False),
        ]),
        ("Profitability", [
            ("ROE", "roe", "pct", True), ("ROA", "roa", "pct", True),
            ("NetMargin", "net_margin", "pct", True),
            ("—", None, None, False), ("—", None, None, False),
        ]),
        ("P&L TTM", [
            ("Rev TTM", "rev_ttm", "money", False), ("Rev YoY", "rev_yoy", "pct", False),
            ("NI TTM", "ni_ttm", "money", False), ("NI YoY", "ni_yoy", "pct", False),
            ("EBITDA", "ebitda", "money", False),
        ]),
        ("Balance Sheet", [
            ("Assets", "assets", "money", False), ("Equity", "equity", "money", False),
            ("Cash", "cash", "money", False), ("DER", "der", "ratio", False),
            ("CR", "cr", "ratio", False),
        ]),
        ("Cash Flow", [
            ("OCF", "ocf", "money", False), ("Capex", "capex", "money", False),
            ("FCF", "fcf", "money", False),
            ("—", None, None, False), ("—", None, None, False),
        ]),
    ]
    ncols = 5
    y = 0.95
    dy = 0.95 / (len(rows) + 0.5)
    for label, cols in rows:
        ax.text(0.005, y, label, color="#58a6ff", fontsize=8, fontweight="bold",
                va="top", transform=ax.transAxes)
        for ci in range(ncols):
            name, key, kind, bench = cols[ci]
            x = 0.16 + ci * 0.168
            if key is None:
                continue
            txt, col = _cell(fin, key, kind, bench)
            ax.text(x, y, f"{name}: ", color="#8b949e", fontsize=7,
                    va="top", transform=ax.transAxes)
            ax.text(x + 0.075, y, txt, color=col, fontsize=7,
                    va="top", transform=ax.transAxes)
        y -= dy


def _header(symbol, signal, snap, fin):
    action = signal.get("action", signal.get("label", ""))
    conf = signal.get("confidence", 0)
    try:
        conf_pct = int(float(conf) * 100) if float(conf) <= 1 else int(float(conf))
    except Exception:
        conf_pct = 0
    score = _num(signal.get("score")) or 0.0
    tech = score
    fund = fund_score(fin)
    g = grade(tech, fund)
    trend = (snap or {}).get("trend_label") or ""
    close = _num(signal.get("close")) or _num((snap or {}).get("close")) or 0.0
    rsi_v = _num(signal.get("rsi")) or _num((snap or {}).get("rsi"))
    rsi_txt = f"{rsi_v:.0f}" if rsi_v is not None else "—"

    fnet = _num((snap or {}).get("foreign_net_5d"))
    if fnet is None:
        flabel = "FA n/a"
    else:
        arrow = "▲" if fnet > 0 else ("▼" if fnet < 0 else "•")
        flabel = f"FA net {arrow} {fmt(abs(fnet), 'money')}"

    return (
        f"{symbol.upper()} — {action} {conf_pct}% Score {score:.0f}/100 {g} "
        f"T:{tech:.0f} F:{fund:.0f} | ◉ {trend} | Close {close:,.0f} | "
        f"RSI {rsi_txt} | {flabel}"
    )
