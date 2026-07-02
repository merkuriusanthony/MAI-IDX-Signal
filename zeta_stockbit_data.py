#!/usr/bin/env python3
"""Zeta IDX — data layer.
Strategy: Yahoo Finance = base OHLCV (6mo, 120+ bars, no auth).
           Stockbit = overlay foreign flow + broker distribution (auth, ~12 recent days).
Merge by date so feature builder gets full MA/RSI/MACD AND real bandarmologi."""
import urllib.request, urllib.error, json, sys, os, time
sys.path.insert(0, "/opt/data")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
EXODUS = "https://exodus.stockbit.com"


def _stk_token():
    try:
        import stockbit_token as stk, importlib
        importlib.reload(stk)
        return stk.get_access(margin=300)
    except Exception as e:
        sys.stderr.write(f"[stockbit token unavailable: {str(e)[:120]}]\n")
        return None


def _get(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token, "User-Agent": UA,
        "Accept": "application/json", "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/"})
    return json.loads(urllib.request.urlopen(req, timeout=25).read())


# ── Stockbit endpoints ──────────────────────────────────────────────────────

def price_feed(symbol, token=None):
    token = token or _stk_token()
    if not token: return None
    return _get(f"{EXODUS}/company-price-feed/historical/summary/{symbol}", token)


def broker_distribution(symbol, token=None):
    token = token or _stk_token()
    if not token: return None
    return _get(f"{EXODUS}/order-trade/broker/distribution?symbol={symbol}", token)


def orderbook(symbol, token=None):
    token = token or _stk_token()
    if not token: return None
    return _get(f"{EXODUS}/company-price-feed/v2/orderbook/companies/{symbol}", token)


# ── Yahoo Finance OHLCV (no auth, 6mo default) ─────────────────────────────

def yahoo_ohlcv(symbol, rng="6mo", interval="1d"):
    """Returns list[dict] sorted oldest→newest: {date,open,high,low,close,volume}"""
    return _yahoo_ohlcv_url(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.JK?range={rng}&interval={interval}")

def _yahoo_ohlcv_url(url):
    import datetime
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=25).read())
    res = r["chart"]["result"][0]
    ts_list = res["timestamp"]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts_list):
        if q["close"][i] is None:
            continue
        dt = datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        out.append({"date": dt, "open": q["open"][i], "high": q["high"][i],
                    "low": q["low"][i], "close": q["close"][i], "volume": q["volume"][i]})
    return sorted(out, key=lambda x: x["date"])

def fetch_index(symbol):
    """Fetch index (e.g. IHSG/^JKSE) from Yahoo — same shape as fetch_symbol output."""
    _YAHOO_MAP = {"IHSG": "^JKSE", "JCI": "^JKSE", "LQ45": "^JKLQ45", "IDX30": "^JKIDX30"}
    yticker = _YAHOO_MAP.get(symbol.upper(), symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yticker}?range=1y&interval=1d"
    rows = _yahoo_ohlcv_url(url)
    if not rows:
        raise ValueError(f"No data for index {symbol}")
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else last
    change_pct = ((last["close"] - prev["close"]) / prev["close"] * 100) if prev["close"] else 0
    return {
        "symbol": symbol.upper(),
        "source": "yahoo_index",
        "price_source": "yahoo_index",
        "realtime_price": last["close"],
        "realtime_ts": last["date"],
        "last_close": last["close"],
        "change_pct": round(change_pct, 2),
        "ohlcv": rows,
        "is_index": True,
    }


# ── Go-live fetch: SQLite historical base + Stockbit realtime overlay ───────

def _merge_or_append_today(rows, today_row):
    if not today_row:
        return rows
    rows = list(rows or [])
    for i, r in enumerate(rows):
        if r.get("date") == today_row.get("date"):
            merged = dict(r)
            merged.update({k: v for k, v in today_row.items() if v is not None})
            rows[i] = merged
            return sorted(rows, key=lambda x: x["date"])
    rows.append(today_row)
    return sorted(rows, key=lambda x: x["date"])


def fetch_symbol(symbol):
    """Returns dict for signal engine.

    Go-live architecture:
      - Historical OHLCV + MA100/MA200 base: local SQLite cache (Yahoo backfill + Stockbit daily update)
      - Intraday/current candle: Stockbit orderbook realtime overlay
      - Broker distribution: Stockbit realtime

    Returns:
      ohlcv        : list[dict] oldest→newest; enough bars for MA100/MA200
      foreign      : list[dict] derived from available rows
      broker       : raw Stockbit broker distribution response (or None)
      realtime     : latest Stockbit orderbook snapshot (normalized)
      source       : 'mai_db_realtime' | 'mai_db' | 'yahoo_fallback' | 'none'
      stk_rows     : local rows count
    """
    symbol = symbol.upper().strip()
    result = {"symbol": symbol, "source": "none", "ohlcv": [], "foreign": None,
              "broker": None, "realtime": None, "stk_rows": 0}

    # 1) Preferred: local DB historical base
    try:
        from mai_db import get_ohlcv
        rows = get_ohlcv(symbol, limit=260)
        if rows:
            result["ohlcv"] = rows
            result["source"] = "mai_db"
            result["stk_rows"] = len(rows)
    except Exception as e:
        sys.stderr.write(f"[mai_db {symbol}: {str(e)[:120]}]\n")

    # 2) Fallback if DB not yet backfilled: Yahoo direct
    if not result["ohlcv"]:
        try:
            yrows = yahoo_ohlcv(symbol, rng="1y")
            result["ohlcv"] = yrows
            result["source"] = "yahoo_fallback"
        except Exception as e:
            sys.stderr.write(f"[yahoo fallback {symbol}: {str(e)[:100]}]\n")

    # 3) Realtime Stockbit overlay (orderbook → virtual today candle)
    #    REQUIREMENT: every analysis uses Stockbit realtime current price, never stale.
    #    We explicitly force the latest bar's close to the realtime last_price.
    try:
        from mai_realtime import update_realtime_snapshot, get_virtual_today_candle
        snap = update_realtime_snapshot(symbol)
        result["realtime"] = snap
        today_row = get_virtual_today_candle(symbol)
        if today_row:
            result["ohlcv"] = _merge_or_append_today(result["ohlcv"], today_row)
            result["source"] = "mai_db_realtime" if result["source"].startswith("mai_db") else result["source"] + "+realtime"
        # Explicit injection: guarantee last close == Stockbit realtime price.
        if snap and snap.get("last_price"):
            result["realtime_price"] = float(snap["last_price"])
            result["price_source"] = "stockbit_realtime"
            import datetime as _dt, zoneinfo as _zi
            result["realtime_ts"] = _dt.datetime.now(_zi.ZoneInfo("Asia/Jakarta")).strftime("%d/%m/%y-%H:%M:%S WIB")
            if result["ohlcv"]:
                result["ohlcv"][-1]["close"] = float(snap["last_price"])
        elif result["ohlcv"]:
            result["realtime_price"] = float(result["ohlcv"][-1].get("close") or 0) or None
            result["price_source"] = result["source"]
    except Exception as e:
        sys.stderr.write(f"[realtime overlay {symbol}: {str(e)[:120]}]\n")
    if "price_source" not in result:
        result["price_source"] = result["source"]
        if result["ohlcv"]:
            result["realtime_price"] = float(result["ohlcv"][-1].get("close") or 0) or None

    # 4) Broker distribution realtime
    token = _stk_token()
    if token:
        try:
            result["broker"] = broker_distribution(symbol, token)
        except Exception as e:
            sys.stderr.write(f"[stockbit broker {symbol}: {str(e)[:100]}]\n")

    # 5) Foreign flow view from merged rows
    result["foreign"] = [
        {"date": r.get("date"), "net_foreign": r.get("net_foreign"),
         "foreign_buy": r.get("foreign_buy"), "foreign_sell": r.get("foreign_sell")}
        for r in result["ohlcv"] if r.get("net_foreign") is not None
    ]

    return result


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BBRI"
    d = fetch_symbol(sym)
    print(f"symbol={d['symbol']} source={d['source']} "
          f"ohlcv_rows={len(d['ohlcv'])} stk_overlay={d['stk_rows']} "
          f"broker={'Y' if d['broker'] else 'N'}")
    last = d["ohlcv"][-1] if d["ohlcv"] else {}
    print("last row:", json.dumps(last, ensure_ascii=False))
