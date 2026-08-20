#!/usr/bin/env python3
"""Zeta Broker Tracker — multi-day activity for a specific broker code.
Shows what a broker (e.g. AK=UBS, XL=Phillip, CC=Mandiri) is buying/selling
market-wide, or filtered to specific symbols, over a date range.

Usage:
  python3 zeta_broker_tracker.py AK                      # today, top net by symbol
  python3 zeta_broker_tracker.py AK --days 5              # last 5 trading days
  python3 zeta_broker_tracker.py AK --symbols BBCA,BUVA   # filter to symbols
  python3 zeta_broker_tracker.py AK --from 2026-07-15 --to 2026-07-22
"""
import sys, os, argparse, json, datetime
sys.path.insert(0, "/opt/data")
import stockbit_token as st
import urllib.request, urllib.error

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
BASE = "https://exodus.stockbit.com"

BROKER_NAMES = {
    "AK": "UBS Sekuritas", "XL": "Phillip Sekuritas", "CC": "Mandiri Sekuritas",
    "ZP": "Maybank Sekuritas", "YP": "Mirae Asset", "BK": "JP Morgan",
    "DX": "BCA Sekuritas", "YU": "CIMB Sekuritas", "MG": "MG Sekuritas",
    "XC": "Phintraco Sekuritas", "PD": "Sinarmas Sekuritas", "AI": "UOB Kay Hian",
}


def _get(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token, "User-Agent": UA,
        "Accept": "application/json", "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/"})
    return json.loads(urllib.request.urlopen(req, timeout=25).read())


def fetch_activity(broker_code, date_from, date_to, token):
    url = f"{BASE}/order-trade/broker/activity?broker_code={broker_code}&from={date_from}&to={date_to}"
    return _get(url, token)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("broker_code")
    p.add_argument("--days", type=int, default=1, help="Trading days lookback (approx calendar days)")
    p.add_argument("--from", dest="date_from", default=None)
    p.add_argument("--to", dest="date_to", default=None)
    p.add_argument("--symbols", default=None, help="Comma-separated symbol filter")
    p.add_argument("--limit", type=int, default=15)
    args = p.parse_args()

    broker = args.broker_code.upper()
    today = datetime.date.today()
    date_to = args.date_to or today.isoformat()
    date_from = args.date_from or (today - datetime.timedelta(days=args.days + 2)).isoformat()

    token = st.get_access()
    try:
        resp = fetch_activity(broker, date_from, date_to, token)
    except urllib.error.HTTPError as e:
        print(f"ERROR {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)

    data = resp.get("data", {})
    bat = data.get("broker_activity_transaction", {})
    buys = bat.get("brokers_buy", []) or []
    sells = bat.get("brokers_sell", []) or []
    broker_name = data.get("broker_name") or BROKER_NAMES.get(broker, broker)

    symbol_filter = None
    if args.symbols:
        symbol_filter = {s.strip().upper() for s in args.symbols.split(",")}

    def agg(rows):
        out = {}
        for r in rows:
            sym = r.get("stock_code")
            if symbol_filter and sym not in symbol_filter:
                continue
            out.setdefault(sym, {"value": 0, "lot": 0})
            out[sym]["value"] += r.get("value", 0) or 0
            out[sym]["lot"] += r.get("lot", 0) or 0
        return out

    buy_agg = agg(buys)
    sell_agg = agg(sells)

    net = {}
    for sym in set(buy_agg) | set(sell_agg):
        b = buy_agg.get(sym, {"value": 0, "lot": 0})
        s = sell_agg.get(sym, {"value": 0, "lot": 0})
        net[sym] = {
            "buy_value": b["value"], "sell_value": s["value"],
            "net_value": b["value"] - s["value"],
            "buy_lot": b["lot"], "sell_lot": s["lot"],
        }

    ranked = sorted(net.items(), key=lambda kv: abs(kv[1]["net_value"]), reverse=True)[:args.limit]

    print(f"📡 Broker Tracker: {broker} ({broker_name})")
    print(f"Period: {date_from} → {date_to}")
    print(f"Symbols tracked: {len(net)}" + (f" (filtered to {sorted(symbol_filter)})" if symbol_filter else " (market-wide)"))
    print()
    for sym, v in ranked:
        direction = "🟢 NET BUY" if v["net_value"] > 0 else "🔴 NET SELL"
        print(f"{sym:<6} {direction:<12} Rp{v['net_value']:>18,.0f}  "
              f"(buy Rp{v['buy_value']:,.0f} / sell Rp{v['sell_value']:,.0f})")


if __name__ == "__main__":
    main()
