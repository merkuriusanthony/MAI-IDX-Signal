#!/usr/bin/env python3
"""CLI: scan the IDX universe once and print the top signals.

Usage:
  python scripts/scan_once.py --mode manual --limit 20 --top 5
  python scripts/scan_once.py --mode manual --limit 5 --top 3 --print-telegram
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ensure data dir exists
os.makedirs("data/charts", exist_ok=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="MAI-IDX-Signal one-shot scanner")
    parser.add_argument("--mode", default="manual", help="Scan mode")
    parser.add_argument("--limit", type=int, default=20, help="Max symbols to scan")
    parser.add_argument("--top", type=int, default=5, help="Top N signals to output")
    parser.add_argument("--no-chart", action="store_true", help="Skip chart generation")
    parser.add_argument("--print-telegram", action="store_true", help="Print Telegram formatted text")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    from app.db import init_db
    await init_db()

    from app.scanner import ScannerService
    scanner = ScannerService(
        mode=args.mode,
        limit=args.limit,
        top_n=args.top,
        generate_charts=not args.no_chart,
    )

    print(f"Scanning {len(scanner.universe)} symbols (mode={args.mode}, top={args.top})...")
    result = await scanner.run()

    signals = result.get("top_signals", [])
    print(
        f"\nScan complete: scanned={result.get('scanned')} "
        f"passed={result.get('passed')} failed={result.get('failed')}"
    )

    if not signals:
        print("No signals generated.")
        return

    if args.json:
        clean = []
        for s in signals:
            sc = {k: v for k, v in s.items() if not k.startswith("_")}
            sc.pop("snapshot", None)
            clean.append(sc)
        print(json.dumps(clean, indent=2, ensure_ascii=False, default=str))
        return

    print("\n=== TOP SIGNALS ===")
    for i, s in enumerate(signals, 1):
        print(
            f"{i:2d}. {s['symbol']:6s} {s.get('action','?'):7s} "
            f"score={s.get('score',0):5.1f} "
            f"entry={s.get('entry',0):>8} "
            f"tp1={s.get('tp1',0):>8} "
            f"sl={s.get('stop_loss',s.get('sl',0)):>8} "
            f"conf={int(float(s.get('confidence',0))*100):3d}% "
            f"rr={s.get('risk_reward',0):.2f}"
        )
        if s.get("chart_path"):
            print(f"     chart: {s['chart_path']}")

    if args.print_telegram:
        from app.signals.renderer import format_scan_summary
        print("\n=== TELEGRAM PREVIEW ===")
        print(format_scan_summary(signals, mode=args.mode))


if __name__ == "__main__":
    asyncio.run(main())
