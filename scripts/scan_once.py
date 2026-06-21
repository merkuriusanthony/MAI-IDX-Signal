#!/usr/bin/env python3
"""CLI: scan the universe once and print the top signals."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.data.universe import load_universe  # noqa: E402
from app.signals.generator import generate_signals  # noqa: E402


async def main() -> None:
    universe = load_universe()[:10]
    print(f"Scanning {len(universe)} symbols: {', '.join(universe)}")
    signals = await generate_signals(universe, top_n=5)
    if not signals:
        print("No signals generated (no data?).")
        return
    print("\n=== TOP 5 ===")
    for i, s in enumerate(signals, 1):
        print(
            f"{i}. {s['symbol']:6s} {s['label']:6s} "
            f"score={s['score']:5.1f} entry={s['entry']} "
            f"tp1={s['tp1']} sl={s['sl']} conf={s['confidence']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
