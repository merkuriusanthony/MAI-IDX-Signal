# MAI-IDX-Signal — Phase 5+ Technical Review & Improvement Roadmap

**Scope:** Deep technical review of `app/` (v0.6.0, ~14k LOC). Focus: what the *next* improvement phase should attack. Each section states **current state** (with file/function citations), **the gap**, and a **concrete recommendation**.

**TL;DR severity ranking:**

| # | Area | Severity | One-line problem |
|---|------|----------|------------------|
| 1 | Backtest rigor | 🔴 Critical | No fees/slippage, survivorship bias, no walk-forward/OOS → reported win-rate is fiction |
| 2 | Data / corporate actions | 🔴 Critical | `auto_adjust=False` + `adj_close` dropped → splits/dividends corrupt all history-based indicators |
| 3 | Signal quality | 🟠 High | No regime detection, no vol-adjusted sizing, momentum/mean-reversion fused, two placeholder buckets (12 free pts) |
| 4 | AI layer | 🟠 High | Claude is decoration — paraphrases deterministic reasons, adds zero alpha |
| 5 | Architecture/scale | 🟡 Medium | Sync `yfinance` in async sem, no shared in-run cache, SQLite write contention |
| 6 | Product gaps | 🟡 Medium | No portfolio risk, no position sizing, no paper-trading ledger, naive tracker |

---

## 1. SIGNAL QUALITY — `app/analytics/scoring.py`, `indicators.py`

### Current state
- `score_snapshot()` (`scoring.py:59`) starts at 50 and adds bounded buckets: Trend (±25), Momentum (±20), Liquidity (±15), Risk (±15), plus **two hardcoded placeholders**: market/sector `+5` (`:214`) and flow `+7` (`:219`). Thresholds map score→action (`_THRESHOLDS`, `:17`).
- Indicators (`indicators.py`): SMA, Wilder RSI, MACD, ATR (EWM), stochastic, naive support/resistance (60-bar min/max), fib. RSI edge cases handled correctly (`:36-38`).
- `gorengan_penalty()` (`scoring.py:32`) subtracts up to 50 pts for penny/illiquid/volume-spike/extreme-move characteristics — applied in scanner, **not** inside `score_snapshot`.

### Gaps
1. **12 phantom points.** Market/sector (`+5`) and flow (`+7`) buckets are constants. Every stock gets them, so they shift the mean but add no discrimination — yet they push borderline names over the WATCH/BUY thresholds (60/75). Dead weight masquerading as signal.
2. **No regime detection.** Same long-only momentum logic fires in a bull and a bear market. No IHSG/index trend filter, no breadth, no volatility regime (VIX-equivalent). In a downtrend the model will keep emitting BUYs on every MA20 cross.
3. **Momentum and mean-reversion are fused and self-contradictory.** RSI 50–70 rewarded (`+8`), RSI<30 *penalized* (`-5`, `:123`) — that's a pure momentum stance. But the Risk bucket *rewards* "near support" (`+7`) and Stoch<20 (`+4`, `:203`) — that's mean-reversion. A single score can't be both; they cancel and produce mush. No separation of strategy archetype.
4. **No volatility-adjusted anything.** ATR only gates score (penalty). It is **not** used to size positions, normalize returns, or set regime-aware thresholds. A 2%-ATR blue chip and an 8%-ATR small cap are scored on the same 0–100 scale with the same TP/SL geometry intent.
5. **No multi-timeframe confirmation.** Everything is daily (`interval="1d"` everywhere). No weekly trend filter, no intraday confirmation. A daily breakout against a weekly downtrend looks identical to one with the tide.
6. **Naive support/resistance.** `support_resistance()` = rolling min/max over 60 bars. No swing-pivot detection, no volume-at-price, no clustering. The single lowest tick anchors "support" — fragile.
7. **Linear additive model, never calibrated.** Weights (6/5/8 for MAs, 8/7 for RSI/MACD) are hand-picked, never fit to outcomes. No evidence these weights beat equal-weight or a coin flip. The backtest exists but **does not feed back** into weighting.
8. **Look-ahead-free but stateless.** Scoring sees only the latest bar's snapshot — no trend persistence, no "how long above MA200", no acceleration.

### Recommendations
- **Delete the placeholder buckets** or wire them to real data. Sector: rank the symbol's sector by 20d relative strength vs IHSG and award real points. Flow: if foreign-flow/bandarmology data is unavailable, remove the +7 rather than gifting it.
- **Add a market-regime gate** as a top-level multiplier, not a bucket. Compute IHSG (`^JKSE`) MA50/MA200 + 20d realized vol once per scan; in a risk-off regime, suppress BUY (downgrade to WATCH) and tighten thresholds. This is the single highest-ROI signal-quality change.
- **Split into two scorers** — `score_momentum()` and `score_meanreversion()` — and tag each signal with its archetype. Let regime select which is active (momentum in trending/low-vol, mean-reversion in choppy/range). Stop summing contradictory evidence.
- **Volatility-normalize.** Express TP/SL purely in ATR multiples (entry ± k·ATR) and report an ATR-scaled "edge" so cross-sectional scores are comparable. Feed ATR into position sizing (see §6).
- **Multi-timeframe filter:** fetch weekly (resample daily→`W`) and require weekly close > weekly MA20 for a BUY. Cheap, high-precision filter.
- **Calibrate weights against backtest outcomes** (logistic regression of features → P(win) on the OOS set, see §2). Replace hand-tuned constants with fitted coefficients; keep the additive form for explainability.
- Upgrade support/resistance to **swing-pivot + volume cluster** detection.

---

## 2. BACKTEST RIGOR — `app/backtest/engine.py`, `routes.py`

### Current state
- `run_backtest()` (`engine.py:23`) walks `for i in range(lookback, len-hold_max-1)`, scores `df.iloc[:i]` (strictly past data), and **only on `action=="BUY"`** simulates a trade entering at `hist.close.iloc[-1]`, scanning the next `hold_max=20` bars for SL → TP2 → TP1 (`:63-72`).
- `summarize()` (`:90`) reports win_rate, avg_return, "max_drawdown" (which is actually just the single worst trade's pnl, `:97`).
- Default run: `load_universe()[:50]`, 90 days (`routes.py:117, 248`). Background task, WAL-mode SQLite.

### What it gets right
- **No lookahead in scoring** — `df.iloc[:i]` excludes the current/future bar. Good.
- Entry at signal-bar close, exit over *subsequent* bars — temporally sound.
- Intrabar fill order checks **SL before TP** (`:64` before `:67`) — conservative on the downside.

### Gaps (these invalidate the reported numbers)
1. **Zero transaction costs.** No brokerage fee, no IDX levy, no spread, no slippage. IDX retail round-trip is ~0.3–0.4% fee + spread; on 7% TP targets that's a material haircut, and it disproportionately kills the high-frequency low-edge trades. **Reported avg_return is upward-biased by roughly the cost-per-trade × turnover.**
2. **Survivorship bias.** Universe is a *current* static text file (`universe.py` reads one symbol/line). Delisted/suspended names are absent, so the backtest only ever sees stocks that survived to today — systematically overstating returns.
3. **No walk-forward / no out-of-sample.** The same hand-tuned weights are evaluated on the same period they were (implicitly) designed against. There is no train/test split, no rolling re-fit, no holdout. Any "good" result is in-sample overfit.
4. **"max_drawdown" is mislabeled** (`:97`). It's `min(trade pnl)` — the worst *single* trade, not equity-curve drawdown. There is no equity curve at all, so no true MDD, no Sharpe/Sortino, no exposure/concurrency accounting.
5. **Optimistic TP-vs-TP ordering.** Within a bar it checks `high>=tp2` before `high>=tp1` (`:67-70`), so a bar that spans both books the *better* TP2. Combined with no modeling of gap-throughs, exits are rosy.
6. **Fills assume infinite liquidity at exact level.** TP/SL fill at the precise theoretical price; no gap-down-through-stop (you'd fill worse), no partial fills, no volume cap.
7. **Win-rate counts `pnl>0`** (`summarize`), but "expired" trades exit at close — a +0.1% expiry counts as a win identical to a TP2. No expectancy decomposition.
8. **Only BUY is tested.** WATCH/HOLD signals never simulated, so you can't measure whether the action thresholds (60/75) are well-placed.

### Recommendations
- **Add a cost model** to `run_backtest`: parametrize `fee_bps` (entry+exit) and `slippage_bps`, subtract from every `pnl_pct`. Default to realistic IDX retail figures. This alone will reorder the strategy's apparent viability.
- **Build a point-in-time universe** to kill survivorship: snapshot the IDX listing per month (or at minimum, include known delistings). Short of full PIT data, *document* the bias prominently in the dashboard.
- **Walk-forward harness:** split history into rolling train/test windows; fit weights (or just thresholds) on train, evaluate on test, roll forward. Report **OOS** metrics only. This is the credibility unlock for the whole product.
- **Real equity curve + metrics:** simulate a portfolio with position sizing and max-concurrent-positions, then compute true max-drawdown, Sharpe, Sortino, profit factor, expectancy, and exposure. Rename the current field — it is not drawdown.
- **Pessimistic fills:** on gap-through-SL, fill at the bar's open (or low), not the stop level; check TP1 before TP2 within a bar.
- Backtest the **full universe**, not just top-50, and across multiple regimes (2020 crash, 2021 bull, 2022–23 chop) to expose regime fragility.

---

## 3. AI LAYER — `app/ai/`

### Current state
- `call_claude()` (`claude_client.py:38`) — async httpx POST to Anthropic Messages API, strict-JSON parse, deterministic `_fallback()` on any error. Robust plumbing.
- `build_signal_prompt()` (`prompts.py:26`) feeds Claude the **already-computed** score, action, reason_codes, and indicator values, with rules: "do not invent numbers, do not change entry/TP/SL, reply JSON only" (`SYSTEM_INSTRUCTION`).
- **Sole call site:** `generator.py:107-117`, only when `with_ai=True` *and* action ∈ {BUY, WATCH}. Output is used for `summary` text and to *prepend* `key_reasons` to the deterministic reasons list (`:114-115`).

### Gap — Claude is decoration, not alpha
The model is handed the conclusion and asked to narrate it. By construction (prompt rule #3) it cannot change the verdict, the score, or the levels. It paraphrases `reason_codes` into Indonesian prose. The `RESPONSE_SCHEMA` even has a `verdict: valid|caution|reject` field that **is never read** by `generator.py` — the AI's actual judgment is discarded. Net contribution to signal quality: **zero**. It's a (paid, latency-adding) text formatter that a Jinja template could replace.

### Recommendations — where Claude could add *real* alpha
1. **News & filing sentiment** (highest value). IDX issuers publish disclosures (IDX/keterbukaan informasi), and there's a steady Indonesian-language news flow. Fetch headlines/filings per candidate, have Claude classify materiality + directional sentiment + event type (rights issue, M&A, earnings, dividend, lawsuit). This is genuinely orthogonal to price-derived indicators and is exactly what an LLM is good at. Feed it back as a real scoring input or a veto.
2. **Earnings interpretation.** When a candidate has a recent earnings release, have Claude read the financials/management commentary and emit a structured surprise/quality read. Use it to gate momentum signals (avoid buying a technical breakout into deteriorating fundamentals).
3. **Regime narration + cross-sectional reasoning.** Give Claude the *whole* candidate set + index regime and ask it to flag crowding, sector concentration, and "this looks like a sector rotation" — qualitative pattern work the additive scorer can't do.
4. **Make the AI verdict count.** Actually consume the `verdict` field: let `reject` downgrade a BUY to WATCH (with the reason surfaced). If you trust it enough to display it, trust it enough to act on it — and then backtest the AI-gated variant vs the deterministic one to *prove* the lift.
5. **Cost/latency:** use the cheapest capable model (`claude-haiku-4-5`) for per-symbol sentiment fan-out, reserve a stronger model for the once-per-scan regime/portfolio synthesis. Add response caching keyed on (symbol, date, news-hash).

> Note: `claude_client.py` sends both `x-api-key` and `Authorization: Bearer` headers (`:59-60`) — harmless but confused; pick one per the actual endpoint.

---

## 4. DATA — `app/data/`

### Current state
- Single source: Yahoo via `yfinance` (`fetch_yahoo.py:74`). 3× retry on "429" with exponential backoff (`:72-88`). Parquet file cache (30-min TTL, `/tmp`, `:13-14`) + SQLite OHLCV cache (`save_ohlcv`).
- Universe from a flat text file (`universe.py`). Sectors/boards from static generated maps (`idx_sectors.py`, 4800+ lines).

### Gaps
1. **Corporate actions are mishandled — this corrupts the indicators.** `yf.download(..., auto_adjust=False)` (`:79`) returns *raw* OHLC, and the column filter `keep = [open,high,low,close,volume]` (`:110`) **drops `adj_close`**. So every MA, RSI, MACD, ATR is computed on **unadjusted** prices. On a stock split or large dividend, raw close gaps mechanically → false breakdown/breakout, garbage ATR spike, wrong MA crosses. For a 963-symbol IDX universe (frequent stock splits and rights issues), this silently poisons signals around every corporate action. **High-severity correctness bug, not just a gap.**
2. **Single point of failure.** Yahoo is the only source. If Yahoo throttles/blocks (common for `.JK` bulk), the entire scan degrades to empty frames → silently fewer candidates, no alert.
3. **No data-quality validation.** No checks for stale data (last bar age), zero-volume halted days, suspicious 1-tick prints, or duplicated dates. Halted/suspended IDX names will pass through with stale closes.
4. **`/tmp` cache is ephemeral.** Lost on restart; on many hosts `/tmp` is also size-capped. 30-min TTL means intraday cron scans re-hammer Yahoo.
5. **Per-symbol sequential downloads.** `yf.download` is called once per symbol (963 round-trips), not batched.

### Recommendations
- **Fix corporate actions now:** set `auto_adjust=True` (or keep `adj_close` and compute indicators on it). At minimum, scale OHLC by `adj_close/close` so the whole bar is split/dividend-consistent. This is a small change with outsized correctness impact — do it before any scoring rework.
- **Add a second source / fallback** (e.g., Stooq, an IDX vendor, or a broker API) behind the `fetch_ohlcv` interface, with source-priority and health tracking. Surface "data degraded" on the status page when fallbacks fire.
- **Data-quality gate** in `fetch_ohlcv_safe`: reject snapshots whose last bar is older than N trading days, flag zero-volume tails, dedupe dates. Currently `min_rows` is the only guard.
- **Persist the cache** off `/tmp` and lengthen TTL for closed-market hours (no point refetching EOD data every 30 min overnight).
- **Batch downloads** (yfinance multi-ticker) or reuse the SQLite OHLCV cache as the primary store with incremental top-up, fetching only missing recent bars.
- Add **corporate-action awareness**: log split/dividend events so the tracker (§6) doesn't mark a split-day as an SL hit.

---

## 5. ARCHITECTURE / SCALE — scanner, db, scheduler

### Current state
- `ScannerService.run()` (`scanner.py:56`) fans out all 963 symbols as asyncio tasks under a `Semaphore(SCAN_CONCURRENCY)` (`:69`), `gather`s all, scores, saves candidates, then builds top-N full signals.
- DB: async SQLAlchemy + aiosqlite, **WAL enabled** (`db.py:239`) — good, lets backtest writers and readers coexist.
- Scheduler: APScheduler cron jobs (pre-market 08:30, opening 09:15, EOD 16:05, hourly intraday 09–16 WIB; `jobs.py:66-83`).

### Gaps
1. **Blocking I/O inside async.** `fetch_ohlcv_safe` is **synchronous** (`yfinance`, parquet, file I/O) but is called directly inside the async `_process` coroutine (`scanner.py:74`). It blocks the event loop for the duration of each network call; the `Semaphore` bounds concurrency but the sync calls still serialize on the single thread. The "concurrency" is largely illusory — true parallelism needs `run_in_executor`/threadpool or an async HTTP client.
2. **No shared in-run cache / double-fetch.** Scanner fetches each symbol once for scoring, then `_build_one` (`generator.py:86`) **fetches the same symbol again** from scratch for the top-N (parquet cache mitigates but still re-parses). The `_df` is even carried on the candidate dict (`scanner.py:134`) but `_build_one` ignores it and re-fetches.
3. **DB write pattern.** Candidates saved in a serial loop (`scanner.py:148-152`), one transaction per row. For 963 symbols that's hundreds of round-trips. SQLite + WAL handles it but it's avoidable latency; batch inserts would help.
4. **Whole universe held in memory** with `_df` DataFrames attached (`scanner.py:134`) until top-N selection — memory scales with universe × history.
5. **No scan-level caching of the index/regime** computation (would be computed per-symbol if added naively).
6. **SQLite write contention ceiling.** Fine now; if scan + backtest + tracker + API writes grow, a single-writer SQLite becomes the bottleneck. WAL helps reads, not concurrent writes.

### Recommendations
- **Offload sync fetch to a threadpool:** `await loop.run_in_executor(pool, fetch_ohlcv_safe, sym)` so the semaphore actually buys parallelism. Biggest latency win.
- **Reuse the fetched DataFrame:** pass `cand["_df"]`/`_snap` into `_build_one` instead of re-fetching. Eliminates the entire second fetch pass for top-N.
- **Batch candidate inserts** (`save_scan_candidate` → bulk `add_all` / executemany) in one transaction.
- **Stream/drop `_df`** after scoring; keep only top-N frames to cap memory.
- Compute **index regime once per run** and pass into scorers.
- Plan a **Postgres migration path** if concurrent writers grow; keep the SQLAlchemy layer source-agnostic so it's a config change.

---

## 6. PRODUCT GAPS — tracking, risk, paper trading

### Current state
- `tracker.py`: `update_all_open_signals()` (`:86`) refetches 5-day data for open signals and sets status TP1/TP2/stopped/expired via `_update_signal_full` (`:132`). `get_performance_summary()` (`:192`) aggregates win-rate/avg-pnl across Tracking.
- Signals carry entry/TP1/TP2/SL/invalidation/risk_reward (`generator.py:_levels`).

### Gaps
1. **Tracker uses 5-day aggregate min/max, not path-correct.** `_update_signal_full` is fed `latest_high = df["high"].max()` / `min` over **5 days** (`tracker.py:101-102`). If both TP1 and SL were touched in that window it can't tell order — and it checks TP2→TP1→SL on the *latest close* anyway (`:148-153`), so a stock that hit TP2 intraday then closed below entry may be recorded as "open". Same intrabar-ambiguity problem as the backtest, but worse because it's coarser.
2. **No position sizing.** Signals give levels but never a size. Without ATR/volatility-based sizing there's no risk parity — a 2% SL and an 8% SL signal would risk wildly different capital if equally weighted.
3. **No portfolio-level risk.** No max concurrent positions, no sector-exposure cap, no correlation/heat check, no total-portfolio drawdown limit. Ten BUYs in the same sector = ten correlated bets the system treats as independent.
4. **No paper-trading ledger.** Tracking measures per-signal pnl in isolation; there's no simulated cash account, no equity curve, no realized-vs-unrealized, no commission accounting. Can't answer "if I'd taken every signal with X capital, where would I be?"
5. **No alert lifecycle.** Telegram pushes new signals (`bots/telegram.py`) but there's no TP-hit / SL-hit / invalidation **exit alert** to the user, no de-dup of repeated signals on the same name, no "signal still valid" refresh.
6. **No benchmark.** Performance summary has no comparison to buy-and-hold IHSG — can't tell if the system beats the index.

### Recommendations
- **ATR-based position sizing:** size = (risk_per_trade × equity) / (entry − SL). Emit `suggested_lots` (rounded to IDX 100-share lots) per signal. Turns abstract scores into actionable, risk-equalized trades.
- **Portfolio risk manager:** cap concurrent open positions, cap per-sector exposure, enforce a portfolio heat limit (sum of open risk ≤ X% of equity). Reject/queue signals that breach.
- **Paper-trading ledger:** a `PaperAccount` + `PaperTrade` model with cash, fees, realized/unrealized pnl, and an equity curve. Auto-execute every emitted signal into it. This *is* the live, forward, out-of-sample validation the backtest can't give you — and it's the most credible marketing asset.
- **Exit/lifecycle alerts:** push TP/SL/invalidation events and expiry; de-dup re-signals; send a daily portfolio summary.
- **Path-correct tracking:** store and replay intraday/daily bars since entry in chronological order (reuse the backtest's SL-before-TP intrabar logic) instead of 5-day aggregate min/max.
- **Benchmark everything** against IHSG buy-and-hold in `get_performance_summary` and the dashboard.

---

## Prioritized roadmap (recommended order)

**Phase 5.1 — Correctness (do first, low effort, high impact)**
1. Fix corporate-action adjustment (`auto_adjust=True`/use `adj_close`) — §4. *One-line-ish, unblocks everything downstream.*
2. Add fees + slippage to the backtest, rename fake "max_drawdown" — §2.
3. Reuse fetched DataFrames in scanner→`_build_one`; threadpool the sync fetch — §5.

**Phase 5.2 — Credibility**
4. Walk-forward / OOS backtest harness with real equity-curve metrics (Sharpe, true MDD, expectancy) — §2.
5. Paper-trading ledger as live forward validation — §6.
6. Address survivorship (PIT universe or documented caveat) — §2.

**Phase 5.3 — Edge**
7. Market-regime gate + momentum/mean-reversion split + remove placeholder buckets — §1.
8. ATR position sizing + portfolio risk manager + exit alerts — §6.
9. Calibrate scoring weights against OOS outcomes — §1.

**Phase 5.4 — Differentiation**
10. Make Claude earn its keep: news/filing sentiment + earnings interpretation, AI verdict actually consumed and A/B-backtested — §3.
11. Multi-timeframe (weekly) confirmation; second data source — §1, §4.

---
*Review based on direct reading of `app/analytics/{scoring,indicators}.py`, `app/backtest/{engine,routes}.py`, `app/ai/{claude_client,prompts}.py`, `app/data/{fetch_yahoo,universe}.py`, `app/scanner.py`, `app/signals/{generator,tracker}.py`, `app/db.py`, `app/scheduler/jobs.py`.*
