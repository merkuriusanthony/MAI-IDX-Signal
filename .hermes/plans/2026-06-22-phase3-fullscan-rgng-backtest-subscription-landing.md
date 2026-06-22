# Phase 3 — MAI-IDX-Signal: Full Universe, RG/NG, Backtest, Subscription, Landing

> **For Claude Code:** Implement task by task. Run `uv run pytest -q` after each group. Commit each group.

**Goal:** Ship production-ready platform — 963-saham scanner, RG/NG board data, backtest engine, user subscription/access, landing page + member area.

**Architecture:** FastAPI monolith + SQLite + APScheduler. New modules: `app/backtest/`, `app/subscription/`, `app/pages/`. Full universe switched by env var `SCAN_DEV_LIMIT=0`.

**Tech Stack:** FastAPI, SQLAlchemy async, APScheduler, yfinance, pandas-ta, Jinja2-free HTML (inline), python-telegram-bot (send-only).

**Version:** 0.4.0 → 0.5.0

---

## Group A — Full Universe Scan (963 saham)

### Task A1: Set SCAN_DEV_LIMIT=0 in container env + config default

**Objective:** Enable full 963-symbol scan by default when env is production.

**Files:**
- Modify: `app/config.py` — change `SCAN_DEV_LIMIT` default to `0` (was probably 50/100)
- Modify: `/volume1/docker/mai-idx-signal/.env` on NAS — add `SCAN_DEV_LIMIT=0`

**Implementation:**
```python
# app/config.py — find SCAN_DEV_LIMIT field
SCAN_DEV_LIMIT: int = int(os.getenv("SCAN_DEV_LIMIT", "0"))
```

**Verify:** `curl -s -X POST http://localhost:8000/api/scan -H 'Content-Type: application/json' -d '{"mode":"manual","limit":963}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['universe_count'])"` → must print `963`.

### Task A2: Tune concurrency for 963-symbol scan

**Objective:** Scan 963 symbols in <5 min using async batching with yfinance.

**Files:**
- Modify: `app/config.py` — `SCAN_CONCURRENCY` default to `20`
- Modify: `app/scanner.py` — add progress logging every 100 symbols

**Implementation in scanner.py `_process`:**
```python
if scanned % 100 == 0:
    logger.info("[scanner] progress %d/%d", scanned, universe_count)
```

**Verify:** Full scan log shows `progress 100/963`, `200/963`, ... `900/963`.

### Task A3: Batch Yahoo fetch with retry + rate-limit guard

**Objective:** Prevent 429 errors on full scan; retry up to 3x with backoff.

**Files:**
- Modify: `app/data/fetch_yahoo.py` — wrap `yf.Ticker().history()` with retry logic

**Implementation:**
```python
def fetch_ohlcv_safe(symbol: str, period: str = "6mo", retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            df = yf.Ticker(f"{symbol}.JK").history(period=period, auto_adjust=True)
            if df.empty:
                return {"ok": False, "df": None, "value_estimate": 0}
            # ... existing logic
            return {"ok": True, "df": df, "value_estimate": value_est}
        except Exception as e:
            if "429" in str(e) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"ok": False, "df": None, "value_estimate": 0}
```

**Test:**
```python
def test_fetch_retry_on_empty():
    from app.data.fetch_yahoo import fetch_ohlcv_safe
    r = fetch_ohlcv_safe("XXXX_NOT_REAL")
    assert r["ok"] is False
```

**Commit:** `feat: full 963-symbol scan with retry guard`

---

## Group B — RG/NG Board Data

### Task B1: Add RG/NG board flag to sector data

**Objective:** Tag each symbol with board: RG (Regular), NG (Negotiated), TN (Tunai).

**Files:**
- Create: `app/data/boards.py`
- Modify: `app/data/sectors.py` — add `get_board(symbol)` helper

**Implementation `app/data/boards.py`:**
```python
"""IDX board classification: RG (Regular), NG (Negotiated), TN (Tunai), etc."""
# Most liquid 963 symbols are RG. NG/TN are special.
# Source: IDX public data (static list, update quarterly).
NG_SYMBOLS = {"DNAR", "OCAP", "MPRO", ...}  # expand via IDX crawl
TN_SYMBOLS: set = set()

def get_board(symbol: str) -> str:
    s = symbol.upper().replace(".JK", "")
    if s in NG_SYMBOLS:
        return "NG"
    if s in TN_SYMBOLS:
        return "TN"
    return "RG"
```

**Modify `app/data/sectors.py`:**
```python
from app.data.boards import get_board
def get_profile(symbol: str) -> dict:
    d = IDX_SECTORS.get(symbol.upper().replace('.JK', ''), {...})
    d["board"] = get_board(symbol)
    return d
```

### Task B2: Show RG/NG badge on dashboard signal table

**Objective:** Signal table and detail page show board badge (RG/NG/TN).

**Files:**
- Modify: `app/dashboard/routes.py` — `index()` + `signal_detail()` — add board badge

**Implementation:**
```python
# In index() cell builder:
from app.data.sectors import get_profile
profile = get_profile(s.symbol)
board = profile.get("board", "RG")
board_color = {"RG": "text-blue-400", "NG": "text-orange-400", "TN": "text-yellow-400"}.get(board, "")
# Add board cell to table row
```

### Task B3: /rgng Telegram command

**Objective:** `/rgng TICKER` returns board + context.

**Files:**
- Modify: `app/bots/telegram.py` — add handler `cmd_rgng`

**Implementation:**
```python
async def cmd_rgng(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /rgng TICKER")
        return
    symbol = context.args[0].upper()
    from app.data.boards import get_board
    board = get_board(symbol)
    await update.message.reply_text(f"{symbol} board: *{board}*", parse_mode="Markdown")
```

**Test:**
```python
def test_get_board_rg():
    from app.data.boards import get_board
    assert get_board("BBCA") == "RG"
```

**Commit:** `feat: RG/NG board data + badge + /rgng command`

---

## Group C — Backtest Engine

### Task C1: Backtest model + DB table

**Objective:** Store backtest runs and results in SQLite.

**Files:**
- Modify: `app/models.py` — add `BacktestRun`, `BacktestResult` SQLAlchemy models
- Modify: `app/db.py` — add `create_backtest_run()`, `save_backtest_result()`, `get_backtest_results()`

**Models:**
```python
class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    strategy: Mapped[str] = mapped_column(String(64))
    universe_size: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[str] = mapped_column(String(16))
    end_date: Mapped[str] = mapped_column(String(16))
    total_signals: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_return: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="running")
    created_at: Mapped[str] = mapped_column(String(32), default="")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")

class BacktestResult(Base):
    __tablename__ = "backtest_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"))
    symbol: Mapped[str] = mapped_column(String(16))
    entry_date: Mapped[str] = mapped_column(String(16))
    exit_date: Mapped[str] = mapped_column(String(16))
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    pnl_pct: Mapped[float] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(16))  # tp1/tp2/sl/expired
    score: Mapped[float] = mapped_column(Float)
    sector: Mapped[str] = mapped_column(String(64), default="Unknown")
```

### Task C2: Backtest engine core

**Objective:** Replay scoring engine on historical data, simulate TP/SL hits.

**Files:**
- Create: `app/backtest/engine.py`

**Implementation:**
```python
"""Vectorized backtest: replay scoring on historical OHLCV, simulate TP/SL."""
import pandas as pd
import numpy as np
from app.analytics.indicators import compute_features
from app.analytics.scoring import score_snapshot
from app.data.sectors import get_sector

def run_backtest(
    symbol: str,
    df: pd.DataFrame,
    lookback: int = 30,      # days of history to score from
    hold_max: int = 20,      # max holding days
    tp1_pct: float = 0.07,  # 7% TP1
    tp2_pct: float = 0.12,  # 12% TP2
    sl_pct: float = 0.05,   # 5% SL
) -> list[dict]:
    results = []
    for i in range(lookback, len(df) - hold_max - 1):
        hist = df.iloc[:i]
        snap = compute_features(hist, symbol=symbol)
        if not snap.data_ok:
            continue
        score_dict = score_snapshot(snap)
        if score_dict["action"] not in ("BUY",):
            continue
        entry = hist["Close"].iloc[-1]
        tp1 = entry * (1 + tp1_pct)
        tp2 = entry * (1 + tp2_pct)
        sl  = entry * (1 - sl_pct)
        future = df.iloc[i:i + hold_max]
        outcome = "expired"
        exit_price = future["Close"].iloc[-1]
        exit_date = str(future.index[-1])[:10]
        for _, row in future.iterrows():
            if row["Low"] <= sl:
                outcome, exit_price, exit_date = "sl", sl, str(row.name)[:10]
                break
            if row["High"] >= tp2:
                outcome, exit_price, exit_date = "tp2", tp2, str(row.name)[:10]
                break
            if row["High"] >= tp1:
                outcome, exit_price, exit_date = "tp1", tp1, str(row.name)[:10]
                break
        pnl = (exit_price - entry) / entry * 100
        results.append({
            "symbol": symbol, "entry_date": str(hist.index[-1])[:10],
            "exit_date": exit_date, "entry_price": entry, "exit_price": exit_price,
            "pnl_pct": round(pnl, 2), "outcome": outcome, "score": score_dict["score"],
            "sector": get_sector(symbol),
        })
    return results
```

### Task C3: Backtest API endpoint + dashboard page

**Objective:** `POST /api/backtest` triggers run; `/dashboard/backtest` shows results.

**Files:**
- Create: `app/backtest/routes.py` — API + HTML routes
- Modify: `app/main.py` — register backtest router
- Modify: `app/dashboard/routes.py` — add backtest nav link

**API:**
```python
@router.post("/api/backtest")
async def trigger_backtest(symbols: list[str] = None, days: int = 90):
    # run async backtest on given symbols (default: top 50 from universe)
    # store results in DB
    # return summary
    ...
```

**Dashboard `/dashboard/backtest`:**
- Table: symbol, entry, exit, PnL%, outcome, sector
- Summary cards: win rate, avg return, max drawdown, total trades
- Filter by sector, outcome

**Test:**
```python
def test_run_backtest_returns_list():
    from app.backtest.engine import run_backtest
    import pandas as pd, numpy as np
    idx = pd.date_range("2024-01-01", periods=100, freq="B")
    df = pd.DataFrame({
        "Open": np.random.uniform(1000, 1100, 100),
        "High": np.random.uniform(1050, 1150, 100),
        "Low":  np.random.uniform(950, 1050, 100),
        "Close": np.random.uniform(1000, 1100, 100),
        "Volume": np.random.randint(1_000_000, 10_000_000, 100),
    }, index=idx)
    results = run_backtest("BBCA", df, lookback=30, hold_max=5)
    assert isinstance(results, list)
```

**Commit:** `feat: backtest engine + API + dashboard page`

---

## Group D — Subscription & User Access

### Task D1: User model + subscription tiers

**Objective:** Basic user DB with access tier (free, pro, admin).

**Files:**
- Modify: `app/models.py` — add `User` model
- Modify: `app/db.py` — add `create_user()`, `get_user_by_telegram_id()`, `set_user_tier()`

**User model:**
```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    full_name: Mapped[str] = mapped_column(String(128), default="")
    tier: Mapped[str] = mapped_column(String(16), default="free")  # free/pro/admin
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_at: Mapped[str] = mapped_column(String(32), default="")
    expires_at: Mapped[str] = mapped_column(String(32), default="")  # pro expiry
    signal_count: Mapped[int] = mapped_column(Integer, default=0)  # signals sent
```

### Task D2: Access control on signal delivery

**Objective:** Free tier = 2 signals/day max; pro/admin = unlimited.

**Files:**
- Create: `app/subscription/access.py`

**Implementation:**
```python
FREE_DAILY_LIMIT = 2

async def can_receive_signal(telegram_id: int) -> tuple[bool, str]:
    """Returns (allowed, reason)."""
    from app.db import get_user_by_telegram_id
    user = await get_user_by_telegram_id(telegram_id)
    if user is None:
        return True, ""   # new user, allow with auto-register
    if user.tier in ("pro", "admin"):
        return True, ""
    if user.signal_count >= FREE_DAILY_LIMIT:
        return False, f"Batas sinyal gratis {FREE_DAILY_LIMIT}/hari tercapai. Upgrade ke Pro untuk unlimited."
    return True, ""
```

### Task D3: /subscribe Telegram command + admin /grant

**Objective:** Users can see subscription status; admin can grant pro access.

**Files:**
- Modify: `app/bots/telegram.py` — add `cmd_subscribe`, `cmd_grant` handlers

**Implementation:**
```python
async def cmd_subscribe(update, context):
    telegram_id = update.effective_user.id
    user = await get_or_create_user(telegram_id, update.effective_user)
    msg = (
        f"👤 *{user.full_name or user.username}*\n"
        f"Tier: *{user.tier.upper()}*\n"
        f"Sinyal hari ini: {user.signal_count}/{FREE_DAILY_LIMIT if user.tier=='free' else '∞'}\n"
    )
    if user.tier == "free":
        msg += "\nUpgrade ke Pro: hubungi admin."
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_grant(update, context):
    # admin only (check telegram_id == ADMIN_TELEGRAM_ID from config)
    ...
```

**Test:**
```python
def test_access_control_free_limit():
    import asyncio
    from unittest.mock import AsyncMock, patch
    from app.subscription.access import can_receive_signal, FREE_DAILY_LIMIT
    # mock user at limit
    ...
```

**Commit:** `feat: user subscription model + access control + /subscribe command`

---

## Group E — Landing Page + Member Area

### Task E1: Landing page `/`

**Objective:** Public landing page that sells MAI-IDX-Signal.

**Files:**
- Modify: `app/dashboard/routes.py` — change `/` root redirect to `/landing`
- Create: `app/pages/landing.py` — landing page route

**Landing page sections (inline HTML):**
1. Hero: "Scanner Saham BEI 963 Simbol — Real-Time AI Signal"
2. Features: Scan, Chart, Telegram bot, Performance tracker
3. Stats: 963 saham, 92% sektor coverage, 5 signal/hari
4. Tiers: Free (2 signal/day) vs Pro (unlimited + backtest + RG/NG)
5. CTA: "Join Telegram Group" button

**Implementation:**
```python
# app/pages/landing.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def landing():
    return HTMLResponse(LANDING_HTML)

LANDING_HTML = """<!doctype html>..."""  # Full dark Tailwind landing
```

### Task E2: Member area `/member`

**Objective:** Authenticated member dashboard showing personal signal history + PnL.

**Files:**
- Create: `app/pages/member.py`

**Routes:**
- `GET /member?tg_id=<id>` — simple auth via Telegram ID param (MVP, no JWT yet)
- Shows: user tier, signal history, win rate, PnL chart

**Implementation:**
```python
@router.get("/member", response_class=HTMLResponse)
async def member(tg_id: int = 0, db: AsyncSession = Depends(get_session)):
    if not tg_id:
        return HTMLResponse("<p>Login via Telegram: /subscribe</p>")
    user = await get_user_by_telegram_id(tg_id)
    # render personal dashboard
    ...
```

### Task E3: Admin panel `/admin`

**Objective:** Admin-only page: user list, tier management, signal broadcast.

**Files:**
- Create: `app/pages/admin.py`

**Routes:**
- `GET /admin?key=<ADMIN_KEY>` — simple key auth (env var `ADMIN_KEY`)
- Shows: user table, grant pro button, scan trigger, signal log

**Commit:** `feat: landing page + member area + admin panel`

---

## Group F — CI, Tests, Deploy v0.5.0

### Task F1: Write tests for Groups B/C/D/E

**Objective:** Test coverage ≥ 55 passed.

**Files:**
- Create: `tests/test_boards.py` — 3 tests
- Create: `tests/test_backtest.py` — 3 tests
- Create: `tests/test_subscription.py` — 3 tests
- Create: `tests/test_landing.py` — 3 tests

**Verify:** `uv run pytest -q` → ≥ 55 passed.

### Task F2: Bump version to 0.5.0

**Files:**
- Modify: `app/config.py` or `app/main.py` — `VERSION = "0.5.0"`

### Task F3: Commit + push

```bash
git add -A
git commit -m "feat: Phase 3 — full universe, RG/NG, backtest, subscription, landing v0.5.0"
git push origin main
```

**CI must pass before deploy.**

### Task F4: Deploy to NAS

After CI green:
```bash
ssh -i /opt/data/home/.ssh/id_ed25519 hermes@192.168.1.20 \
  "sudo /usr/local/bin/docker compose -f /volume1/docker/mai-idx-signal/docker-compose.yml pull && \
   sudo /usr/local/bin/docker compose -f /volume1/docker/mai-idx-signal/docker-compose.yml up -d --force-recreate"
```

**Verify:**
```bash
curl http://192.168.1.20:7843/health          # {"status":"ok","version":"0.5.0"}
curl -I http://192.168.1.20:7843/             # 200 OK (landing page)
curl http://192.168.1.20:7843/dashboard/backtest  # 200
```

---

## Notes untuk Claude Code

1. Jangan deploy — stop di commit + push. Hermes handle deploy.
2. Setelah tiap Group (A/B/C/D/E/F), run `uv run pytest -q`. Harus green.
3. `app/data/idx_sectors.py` gitignored — skip, pakai `app/data/sectors.py`.
4. Jangan hapus field yang sudah ada di `models.py` — hanya tambah.
5. Full scan 963 simbol butuh `SCAN_DEV_LIMIT=0` di env; jangan hardcode.
6. Landing page pakai Tailwind CDN (sudah ada di dashboard), dark theme.
7. `/admin` key auth via env var `ADMIN_KEY` (default: random UUID dari `settings`).
8. Commit per Group, bukan satu commit besar.
