"""Chart generation using matplotlib."""
from __future__ import annotations

import os
from typing import Dict

import pandas as pd

CHART_DIR = "/app/data/charts"


def generate_chart(symbol: str, df: pd.DataFrame, signal: Dict) -> str:
    """Render a price + MA + volume chart, save PNG, return its path."""
    os.makedirs(CHART_DIR, exist_ok=True)
    out_path = os.path.join(CHART_DIR, f"{symbol.upper()}.png")

    if df is None or df.empty:
        return ""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_df = df.tail(180)
    close = plot_df["close"]
    ma20 = close.rolling(20, min_periods=1).mean()
    ma50 = close.rolling(50, min_periods=1).mean()
    ma200 = close.rolling(200, min_periods=1).mean()

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(11, 7),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    ax1.plot(close.index, close.values, label="Close", color="black", linewidth=1.2)
    ax1.plot(ma20.index, ma20.values, label="MA20", color="tab:blue", linewidth=0.9)
    ax1.plot(ma50.index, ma50.values, label="MA50", color="tab:orange", linewidth=0.9)
    ax1.plot(ma200.index, ma200.values, label="MA200", color="tab:red", linewidth=0.9)

    for key, color, style in (
        ("entry", "green", "--"),
        ("tp1", "blue", ":"),
        ("tp2", "purple", ":"),
        ("sl", "red", "--"),
    ):
        val = signal.get(key)
        if val:
            ax1.axhline(val, color=color, linestyle=style, linewidth=0.8, label=key.upper())

    ax1.set_title(f"{symbol.upper()} — {signal.get('label', '')} (score {signal.get('score', '')})")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.3)

    if "volume" in plot_df.columns:
        ax2.bar(plot_df.index, plot_df["volume"].values, color="gray", width=1.0)
    ax2.set_ylabel("Volume")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    try:
        fig.savefig(out_path, dpi=90)
    finally:
        plt.close(fig)

    return out_path
