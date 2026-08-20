#!/usr/bin/env python3
"""Zeta IDX Screener — full-universe scan filtered by user criteria.
Combines: keystats fundamentals (PER, PBV, ROE, ...) + Stockbit foreign flow (5D net).
Usage:
  python3 zeta_screener.py --per-max 10 --foreign-min 0
  python3 zeta_screener.py --per-max 15 --roe-min 15 --pbv-max 2 --limit 20
  python3 zeta_screener.py --universe-refresh   # re-fetch symbol list from Stockbit

Criteria flags (all optional, AND-combined):
  --per-max / --per-min       PER (x)
  --pbv-max / --pbv-min       PBV (x)
  --roe-min                   ROE (%)
  --der-max                   Debt/Equity (x)
  --div-yield-min             Dividend yield (%)
  --foreign-min                Foreign net 5D (Rp, use negative for outflow filter)
  --ni-yoy-min                 Net income YoY growth (%)
  --rev-yoy-min                 Revenue YoY growth (%)
"""
import sys, os, argparse, json, time
sys.path.insert(0, "/opt/data")
import concurrent.futures as cf
import zeta_financials as zfin
import zeta_stockbit_data as zd
import zeta_idx_universe as zu


def foreign_net_5d(symbol):
    """Sum net_foreign over the most recent 5 rows from price_feed."""
    try:
        pf = zd.price_feed(symbol)
        rows = (pf or {}).get("data", {}).get("result", []) or []
        rows = rows[:5]
        total = sum((r.get("net_foreign") or 0) for r in rows)
        return total
    except Exception:
        return None


def scan_one(symbol, need_foreign):
    try:
        fin = zfin.fetch_financials(symbol)
        r = fin.get("ratios", {})
        p = fin.get("pnl", {})
        row = {
            "symbol": symbol,
            "per": r.get("per_ttm"),
            "pbv": r.get("pbv"),
            "roe": r.get("roe_pct"),
            "der": r.get("der"),
            "div_yield": r.get("dividend_yield_pct"),
            "rev_yoy": p.get("revenue_yoy_pct"),
            "ni_yoy": p.get("net_income_yoy_pct"),
            "foreign_5d": None,
        }
        if need_foreign:
            row["foreign_5d"] = foreign_net_5d(symbol)
        return row
    except Exception as e:
        return {"symbol": symbol, "error": str(e)[:80]}


def passes(row, args):
    if row.get("error"):
        return False
    def chk(val, cmp_min=None, cmp_max=None):
        if val is None:
            return False
        if cmp_min is not None and val < cmp_min:
            return False
        if cmp_max is not None and val > cmp_max:
            return False
        return True

    # Sanity guard: negative PER/PBV/ROE = distressed co. (negative earnings/equity),
    # NOT "cheap". Exclude unless user explicitly wants raw/unfiltered scan.
    if not args.allow_negative:
        per, pbv, roe = row.get("per"), row.get("pbv"), row.get("roe")
        if per is not None and per <= 0:
            return False
        if pbv is not None and pbv <= 0:
            return False
        if roe is not None and roe < -50:  # allow small negative ROE, block extreme distress
            return False

    if args.per_max is not None or args.per_min is not None:
        if not chk(row.get("per"), args.per_min, args.per_max):
            return False
    if args.pbv_max is not None or args.pbv_min is not None:
        if not chk(row.get("pbv"), args.pbv_min, args.pbv_max):
            return False
    if args.roe_min is not None:
        if not chk(row.get("roe"), cmp_min=args.roe_min):
            return False
    if args.der_max is not None:
        if not chk(row.get("der"), cmp_max=args.der_max):
            return False
    if args.div_yield_min is not None:
        if not chk(row.get("div_yield"), cmp_min=args.div_yield_min):
            return False
    if args.ni_yoy_min is not None:
        if not chk(row.get("ni_yoy"), cmp_min=args.ni_yoy_min):
            return False
    if args.rev_yoy_min is not None:
        if not chk(row.get("rev_yoy"), cmp_min=args.rev_yoy_min):
            return False
    if args.foreign_min is not None:
        if not chk(row.get("foreign_5d"), cmp_min=args.foreign_min):
            return False
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--per-max", type=float, default=None)
    p.add_argument("--per-min", type=float, default=None)
    p.add_argument("--pbv-max", type=float, default=None)
    p.add_argument("--pbv-min", type=float, default=None)
    p.add_argument("--roe-min", type=float, default=None)
    p.add_argument("--der-max", type=float, default=None)
    p.add_argument("--div-yield-min", type=float, default=None)
    p.add_argument("--ni-yoy-min", type=float, default=None)
    p.add_argument("--rev-yoy-min", type=float, default=None)
    p.add_argument("--foreign-min", type=float, default=None)
    p.add_argument("--allow-negative", action="store_true", help="Include distressed cos. (negative PER/PBV/ROE)")
    p.add_argument("--sort", choices=["per", "roe", "div_yield", "ni_yoy"], default="per")
    p.add_argument("--limit", type=int, default=30, help="Max results to print")
    p.add_argument("--workers", type=int, default=4, help="Note: keystats endpoint is hard rate-limited (3 req/~34s burst); more workers won't help throughput, just queue behind the shared limiter")
    p.add_argument("--universe-refresh", action="store_true")
    p.add_argument("--universe-file", default=None, help="Comma-separated symbol list override")
    args = p.parse_args()

    if args.universe_file:
        universe = [s.strip().upper() for s in args.universe_file.split(",") if s.strip()]
    else:
        universe = zu.get_universe(refresh=args.universe_refresh)

    need_foreign = args.foreign_min is not None
    print(f"[screener] scanning {len(universe)} symbols (foreign_flow={'on' if need_foreign else 'off'})...", file=sys.stderr)

    results = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(scan_one, s, need_foreign): s for s in universe}
        done = 0
        for fut in cf.as_completed(futs):
            row = fut.result()
            done += 1
            if passes(row, args):
                results.append(row)
            if done % 100 == 0:
                print(f"  [{done}/{len(universe)}] matched={len(results)} elapsed={time.time()-t0:.0f}s", file=sys.stderr)

    # Sort: by chosen metric (desc for quality metrics, asc for PER)
    if args.sort == "per":
        results.sort(key=lambda r: (r.get("per") if r.get("per") is not None else 9e9))
    else:
        results.sort(key=lambda r: (r.get(args.sort) if r.get(args.sort) is not None else -9e9), reverse=True)
    results = results[:args.limit]

    print(f"\n[screener] done in {time.time()-t0:.0f}s — {len(results)} matches (of {len(universe)} scanned)\n", file=sys.stderr)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
