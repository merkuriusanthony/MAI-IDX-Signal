"""Chart generation using matplotlib."""
from __future__ import annotations

import logging
import os
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _chart_dir() -> str:
    from app.config import settings
    d = settings.CHART_DIR
    os.makedirs(d, exist_ok=True)
    return d


def generate_chart(symbol: str, df: pd.DataFrame, signal: Dict) -> str:
    """Render a price + MA + volume chart, save PNG, return its path.

    Returns empty string on failure — never raises.
    """
    if df is None or df.empty:
        return ""

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        logger.warning("matplotlib not available — skipping chart")
        return ""

    chart_dir = _chart_dir()
    out_path = os.path.join(chart_dir, f"{symbol.upper()}.png")

    try:
        plot_df = df.tail(120).copy()
        close = plot_df["close"]

        # compute MAs
        ma20 = close.rolling(20, min_periods=1).mean()
        ma50 = close.rolling(50, min_periods=1).mean()
        ma100 = close.rolling(100, min_periods=1).mean()
        ma200 = close.rolling(200, min_periods=1).mean()

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(12, 7), sharex=True,
            gridspec_kw={"height_ratios": [3, 1]},
        )
        fig.patch.set_facecolor("#0d1117")
        for ax in (ax1, ax2):
            ax.set_facecolor("#0d1117")
            ax.tick_params(colors="white")
            ax.spines[:].set_color("#30363d")

        idx = plot_df.index

        ax1.plot(idx, close.values, label="Close", color="#58a6ff", linewidth=1.4)
        ax1.plot(idx, ma20.values, label="MA20", color="#f0c040", linewidth=0.9, alpha=0.85)
        ax1.plot(idx, ma50.values, label="MA50", color="#f08040", linewidth=0.9, alpha=0.85)
        ax1.plot(idx, ma100.values, label="MA100", color="#8040f0", linewidth=0.8, alpha=0.7)
        ax1.plot(idx, ma200.values, label="MA200", color="#e05050", linewidth=0.9, alpha=0.85)

        for key, color, style, lw in (
            ("entry", "#3fb950", "--", 1.2),
            ("tp1", "#58a6ff", ":", 1.0),
            ("tp2", "#a371f7", ":", 1.0),
            ("stop_loss", "#f85149", "--", 1.2),
            ("sl", "#f85149", "--", 1.2),
        ):
            val = signal.get(key)
            if val and val > 0 and key != "sl":  # prefer stop_loss over sl alias
                ax1.axhline(
                    val, color=color, linestyle=style, linewidth=lw,
                    label=key.upper().replace("_", " "), alpha=0.9,
                )
            elif key == "sl" and not signal.get("stop_loss"):
                if val and val > 0:
                    ax1.axhline(val, color=color, linestyle=style, linewidth=lw, label="SL", alpha=0.9)

        action = signal.get("action", signal.get("label", ""))
        ax1.set_title(
            f"{symbol.upper()}  |  {action}  |  Score {signal.get('score', '')}",
            color="white", fontsize=12,
        )
        ax1.legend(loc="upper left", fontsize=7, facecolor="#161b22", labelcolor="white")
        ax1.grid(True, alpha=0.15, color="#30363d")
        ax1.yaxis.label.set_color("white")

        if "volume" in plot_df.columns:
            colors = ["#3fb950" if c >= o else "#f85149"
                      for c, o in zip(plot_df["close"], plot_df["open"])]
            ax2.bar(idx, plot_df["volume"].values, color=colors, width=0.8, alpha=0.7)
        ax2.set_ylabel("Volume", color="white", fontsize=8)
        ax2.grid(True, alpha=0.15, color="#30363d")

        fig.tight_layout(pad=1.0)
        fig.savefig(out_path, dpi=90, facecolor=fig.get_facecolor())
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
