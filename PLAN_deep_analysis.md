# PLAN — Deep Analysis Feature (5-Panel Chart + Fundamental Table per Signal)

Status: PLAN ONLY. No code written. Mode: implement after approval.

---

## 0. Pre-flight findings (verified against current tree)

Read before coding — these change several task assumptions:

| Assumption in task | Reality in repo | Consequence |
|---|---|---|
| `FeatureSnapshot.ma5` missing | **Already exists** (`indicators.py:128`, computed `:217`, in `to_dict` `:167`) | Skip adding ma5. Only add `foreign_net_5d`, `trend_label`. |
| Add route `GET /dashboard/signal/{id}` | Detail route **already exists**: `GET /dashboard/signals/{signal_id}` (`dashboard/routes.py:249`), already linked from index table (`:127`) | UPGRADE existing route, don't add a duplicate path. Keep `/signals/` (plural) to avoid breaking the existing link. |
| Import `get_access` from `/opt/data/stockbit_token.py` | App already has token resolver `_stockbit_token()` in `app/data/universe_update.py:132`, reading `settings.STOCKBIT_ACCESS_FILE` (`/app/data/.stockbit_access`) then `STOCKBIT_SESSION_COOKIE` | Reuse that pattern in new `app/data/stockbit_auth.py`. Do NOT import outside `/app`. No new config field strictly needed; STOCKBIT_ACCESS_FILE already present. |
| Charts served how? | `chart_router` prefix `/charts/{filename}` in `app/signals/routes.py:189`; img tag `/charts/<basename>` | New API route lives alongside in `app/signals/routes.py`; chart embedding pattern reused. |
| `generate_chart(symbol, df, signal)` callers | One caller: `scanner.py:347`. `signal` is the built signal dict. | New optional kwargs must default to None → zero call-site breakage. |

Stockbit token note: `settings.STOCKBIT_ACCESS_FILE` holds a **bearer JWT string** (host refreshes daily). The standalone `/opt/data/stockbit_token.py` `get_access()` does live refresh but lives outside `/app` (not importable in container). `stockbit_auth.py` will mirror the file-read + cookie-fallback logic already proven in `universe_update.py`.

---

## 1. Architecture Overview

```
                         ┌─────────────────────────────────────┐
                         │  Yahoo OHLCV (existing fetch_yahoo)  │
                         └──────────────────┬──────────────────┘
                                            │ df (OHLCV)
  ┌──────────────────────┐                  ▼
  │ Stockbit API          │      ┌──────────────────────┐
  │ (NEW fetch_stockbit)  │      │ compute_features()    │  (+trend_label,
  │  • keystats ratio     │─fin─▶│  FeatureSnapshot      │   +foreign_net_5d)
  │  • foreign flow        │      └──────────┬───────────┘
  └──────────┬───────────┘  foreign_df       │ snap
             │                                ▼
             │                     ┌──────────────────────┐
             └────────────────────▶│ generate_chart(       │──▶ PNG (5 panel +
              fin, foreign_df       │   df, signal, fin,    │     fundamental table)
                                    │   foreign_df)         │
                                    └──────────┬───────────┘
                                               │ chart_path
                                               ▼
                                    ┌──────────────────────┐
                                    │ Signal row in DB      │
                                    │  snapshot_json += fin │
                                    │  chart_path           │
                                    └──────────┬───────────┘
                       ┌───────────────────────┴────────────────────┐
                       ▼                                             ▼
         GET /dashboard/signals/{id}                  POST /api/analyze/{symbol}
         (upgrade: render fin table +                 (on-demand single-symbol
          embed 5-panel chart)                         deep analysis → JSON)
```

Auth helper (`stockbit_auth.py`) is the single token source for both fetch functions. Token resolution order: `STOCKBIT_ACCESS_FILE` → `STOCKBIT_SESSION_COOKIE` → "" (callers degrade gracefully).

Design invariants:
- `generate_chart` stays total: `fin=None` and `foreign_df=None` must produce a valid chart (panels 1–4; panel 5 + table omitted or shown empty). Never raise — return "" on failure (current contract preserved).
- Stockbit failures NEVER fail a scan. `fin={}` / empty `foreign_df` → chart falls back, signal still saved.
- All Stockbit network calls are blocking-IO wrapped: either `httpx` async client, or `requests`/urllib in `run_in_executor` to match the scanner's executor pattern.

---

## 2. Ordered Task List

> Dependency order. Each task: file · action · depends-on · test gate.

### T1 — `app/data/stockbit_auth.py` (NEW)  ·  deps: none
- `get_token() -> str` — replicate `universe_update._stockbit_token()`:
  1. read `settings.STOCKBIT_ACCESS_FILE` if exists, strip `Bearer ` prefix.
  2. else `settings.STOCKBIT_SESSION_COOKIE`, same stripping.
  3. else `""`.
- `auth_headers(token: str) -> dict` — `{Authorization: Bearer <t>, User-Agent: Mozilla/5.0, Accept: application/json, Origin: https://stockbit.com, Referer: https://stockbit.com/}`.
- Pure stdlib + settings. No network. No duplication of refresh logic (host owns refresh).
- Gate: `py_compile`.

### T2 — `app/data/fetch_stockbit.py` (NEW)  ·  deps: T1
- `BASE = "https://exodus.stockbit.com"`.
- `fetch_keystats(symbol: str, token: str | None = None) -> dict`
  - GET `/keystats/ratio/v1/{SYMBOL}` (SYMBOL upper, no `.JK` suffix — strip if present).
  - Parse + normalize into flat dict with the 21 fields:
    `per, pbv, ev_ebitda, div_yield, eps_ttm, bvps, roe, roa, net_margin,
     rev_ttm, rev_yoy, ni_ttm, ni_yoy, ebitda, assets, equity, cash, der, cr, ocf, capex, fcf`.
  - Robust extraction: Stockbit keystats nests values under labelled groups; walk defensively with a `_pick(data, *path, default=None)` helper + a label→key map. Coerce numerics via `_num()` (handles "1.2x", "14.5%", "1,234", "-", null).
  - On 401/403/timeout/parse-fail → return `{}`, log warning. Never raise.
- `fetch_foreign_flow(symbol: str, token: str | None = None) -> pd.DataFrame`
  - GET `/company-price-feed/historical/summary/{SYMBOL}`.
  - Build DataFrame cols: `date` (datetime index or col), `foreign_buy, foreign_sell, foreign_net`. Derive `foreign_net = buy - sell` if not directly present.
  - On failure → empty DataFrame with those columns. Never raise.
- Shared internal `_get(path, token) -> dict|None` using `httpx.Client` (sync) — callers wrap in executor — OR `httpx.AsyncClient` async variants. **Decision: provide async `fetch_keystats`/`fetch_foreign_flow` using `httpx.AsyncClient`** so generator can `await` directly (scanner already async). Token default: if `None`, call `stockbit_auth.get_token()`.
- Gate: `py_compile`; manual smoke (one symbol) deferred to T9.

### T3 — `app/analytics/indicators.py` (MODIFY)  ·  deps: none (parallel to T1/T2)
- Add fields to `FeatureSnapshot`:
  - `foreign_net_5d: Optional[float] = None`
  - `trend_label: str = ""`   ("UPTREND" / "DOWNTREND" / "SIDEWAYS")
- `trend_label` derivation in `compute_features` from MA stack:
  - UPTREND: `close>ma20>ma50` (and ma200 present → `>ma200`).
  - DOWNTREND: `close<ma20<ma50`.
  - else SIDEWAYS. Guard None MAs (short history → SIDEWAYS).
- `foreign_net_5d`: left `None` here (df has no foreign data). Populated by generator AFTER fetch — set on snap before `to_dict()`, OR injected into snapshot dict in generator. **Decision: keep compute_features pure-technical; generator sets `snap.foreign_net_5d` post-fetch.**
- Update `to_dict()`: add `"trend_label"`, `"foreign_net_5d"`. (fin block added by generator, not here.)
- Gate: `py_compile`; existing scoring untouched (new fields optional, scorer doesn't read them).

### T4 — `app/signals/chart.py` (MODIFY)  ·  deps: T2 (shape of fin/foreign_df), T3 (trend_label)
- New signature:
  `generate_chart(symbol, df, signal, fin=None, foreign_df=None) -> str`
- Restructure to 5 panels via `gridspec` height_ratios ≈ `[40,10,13,17,20]` + extra bottom band for table (use `GridSpec` with a 6th row for the table axes, or `fig.subplots` 5 rows then `fig.text`/`table` below). **Decision: GridSpec 6 rows; row 6 = `ax_table` with `axis('off')` rendering `matplotlib.table` or manual `ax.text` grid.**
- Panel 1 (Price):
  - Close=white `#ffffff`; MA5 `#00d2ff`, MA20 `#ffd700`, MA50 `#ff6b6b`, MA100 `#a855f7`, MA200 `#9ca3af`. (NOTE: colors differ from current MA palette — task spec wins.)
  - MA5 from `df.close.rolling(5)`.
  - Fib dotted levels from `signal["snapshot"]["fib"]` (or recompute via `fib_retracement`); fallback skip if absent.
  - MA crossover markers: detect ma5/ma20 (and ma20/ma50) sign-change of `(ma_a-ma_b)`; ↑green `^`, ↓red `v` at crossover x.
  - Break markers: resistance/support from snapshot; mark bar where `close` crosses `resistance` (Break↑) / `support` (Break↓).
  - Entry/TP1/TP2/SL axhlines (keep existing logic).
- Panel 2 (Volume): green/red bars (existing logic, reuse).
- Panel 3 (RSI): purple line from `rsi(df)`; 70 red-dash, 30 green-dash; ylim 0–100.
- Panel 4 (MACD): MACD blue + signal orange + hist green/red bars; if `foreign_df` non-empty → twin right axis `ax4.twinx()` plotting `foreign_net` (align by date intersection; reindex to df.index, fillna 0). Legend notes right axis = foreign net.
- Panel 5 (PE/PBV Band) — only if `fin` has usable `eps_ttm>0` and/or `bvps>0`:
  - `pe_series = close / eps_ttm` (scalar eps → constant denom; band reflects price variation). Guard `eps_ttm>0` else skip PE.
  - `pbv_series = close / bvps`. Guard `bvps>0`.
  - Plot PE cyan (left axis), PBV amber-dashed (right `twinx`).
  - Bands: mean ±1σ, ±2σ as horizontal dashed lines per series (σ over the plotted window). Label current PE/PBV value.
  - If neither usable → render panel with "Fundamental N/A" centered text (keep layout stable).
- Bottom table (`ax_table`), only if `fin` truthy:
  - 5 rows: **Valuation** (PER, PBV, EV/EBITDA, DivY, EPS) · **Profitability** (ROE, ROA, NetMargin, —, —) · **P&L TTM** (Rev TTM, Rev YoY, NI TTM, NI YoY, EBITDA) · **Balance Sheet** (Assets, Equity, Cash, DER, CR) · **Cash Flow** (OCF, Capex, FCF, —, —).
  - Up to 5 cols each.
  - Verdict tags via helper `_verdict(metric, value)` vs benchmark (see §B): `[+]` above industry (green), `[!]` below (red), `[=]` in-line ±15% (gray). Tag only the benchmarked metrics: PER, PBV, ROE, ROA, NetMargin. Others shown plain.
  - Number formatting helper `_fmt(v, kind)`: ratios `1.2x`, pct `14.5%`, big money → `1.2T/3.4B/5.6M IDR`.
- Header `suptitle` (task format):
  `{SYMBOL} — {ACTION} {confidence}% Score {score}/100 {grade} T:{tech} F:{fund} | ◉ {trend_label} | Close {close} | RSI {rsi} | {foreign_label}`
  - `grade`, `tech`, `fund` sub-scores: derive lightweight — `tech` = signal score (already 0–100), `fund` = fundamental score from `_fund_score(fin)` (count of [+] tags → 0–100), `grade` = A/B/C/D from combined. Document as heuristic. `foreign_label` = `"FA net +X.XB"` from `foreign_net_5d` (▲ inflow / ▼ outflow) or `"FA n/a"`.
- Robustness: wrap each panel in its own try/except so one bad panel can't kill the chart. Keep top-level try/except → "" on total failure. `plt.close("all")` in finally (existing).
- Gate: `py_compile` + render smoke with (a) fin=None, (b) full fin (T9).

### T5 — `app/signals/generator.py` (MODIFY)  ·  deps: T2, T3
- In `_build_one`, after `snap` computed & `data_ok`:
  - Fetch Stockbit (best-effort, never fatal):
    ```
    fin = {}; foreign_df = EMPTY
    try:
        from app.data.fetch_stockbit import fetch_keystats, fetch_foreign_flow
        fin = await fetch_keystats(symbol)
        foreign_df = await fetch_foreign_flow(symbol)
    except Exception: log.warning(...)
    ```
  - Set `snap.foreign_net_5d = last-5-row sum of foreign_df.foreign_net` (guard empty).
  - Extend returned dict: `"fin": fin`, and merge into snapshot: `snap_dict = snap.to_dict(); snap_dict["fin"] = fin; snap_dict["foreign_net_5d"]=snap.foreign_net_5d`.
  - Return also `"_foreign_df": foreign_df` (transient, like scanner's `_df`) so chart call can use it without re-fetch.
- Keep signature/behavior backward compatible. New fetch behind a flag? **Decision: gate with `deep: bool = False` kwarg on `_build_one` (default False) so the bulk scan loop stays fast; only the top-N chart pass + on-demand `/api/analyze` set `deep=True`.** Avoids hammering Stockbit for every candidate.
  - Re-evaluate: scanner only builds top-N via `_build_one` (candidates are scored inline, not via `_build_one`). So `_build_one` is ALREADY only called ≤ top_n + single. Safe to always fetch. **Final: always fetch in `_build_one`; no flag needed.** (Document this — scanner's per-symbol scoring path at `scanner.py:188` does NOT call `_build_one`, so no fan-out cost.)
- Gate: `py_compile`.

### T6 — `app/scanner.py` (MODIFY)  ·  deps: T4, T5
- At chart call `scanner.py:347`, pass fin + foreign_df from the built signal:
  ```
  fin = sig.get("fin")
  fdf = sig.get("_foreign_df")
  chart_path = generate_chart(cand["symbol"], df, sig, fin=fin, foreign_df=fdf)
  ```
- Ensure `_foreign_df` not persisted to DB (strip transient `_`-prefixed keys before `save_signal_dict`, or rely on `save_signal_dict` only reading known keys — it does, so safe; just don't JSON-dump it. `snapshot` already carries `fin`).
- Gate: `py_compile` + one real scan smoke (T9).

### T7 — `app/dashboard/routes.py` (MODIFY)  ·  deps: DB snapshot_json now carries fin
- Upgrade existing `signal_detail` (`:249`, path `/dashboard/signals/{id}`):
  - Parse `snapshot_json` → pull `fin`, `trend_label`, `foreign_net_5d`, levels, fib, support/resistance.
  - Render fundamental table (HTML, Tailwind) with same [+]/[!]/[=] verdicts (shared logic — extract verdict/format helpers into a small module, e.g. `app/analytics/fundamentals.py`, imported by BOTH chart.py and routes.py to avoid divergence).
  - Show levels block: entry/TP1/TP2/SL/invalidation/support/resistance/fib.
  - Embed chart (existing `/charts/<file>` img).
  - Buttons: **Regenerate Chart** → `POST /dashboard/signals/{id}/regenerate` (new small route: reload df from OHLCV cache or re-fetch, re-run generate_chart, update chart_path). **Back** → `/dashboard`.
- Index table link already exists (`:127`) — no change.
- Gate: `py_compile`; visual check (T9).

### T8 — NEW shared module `app/analytics/fundamentals.py` (NEW)  ·  deps: none (do early, before T4/T7)
> Promote this BEFORE T4/T7 to avoid duplicating verdict/format logic.
- `BENCHMARK = {"per":14.0,"pbv":1.8,"roe":14.0,"roa":5.0,"net_margin":10.0}` (§B).
- `verdict(metric: str, value: float|None) -> str` → `"+" | "!" | "=" | ""`.
  - Direction-aware: for PER/PBV **lower is better** (below benchmark = `[+]`); for ROE/ROA/NM **higher is better** (above = `[+]`). In-line band ±15%.
- `fmt(value, kind) -> str` (kind in {ratio, pct, money}).
- `fund_score(fin: dict) -> float` 0–100 from count/weight of `[+]` vs `[!]`.
- `grade(tech: float, fund: float) -> str` A/B/C/D.
- Reused by chart table, dashboard table, and `/api/analyze`. Single source of truth.
- Gate: `py_compile` + tiny inline self-test of verdict directions.

### T9 — Integration smoke + compile gate  ·  deps: all
- `python3 -m py_compile` on every touched/new file (one command).
- Token presence check: `python3 -c "from app.data.stockbit_auth import get_token; print(bool(get_token()))"`.
- One live symbol (e.g. BBCA): call `fetch_keystats`+`fetch_foreign_flow`, assert keys/cols.
- Render chart twice: `fin=None` path and full path; assert PNG non-empty bytes.
- One `POST /api/analyze/BBCA` and load `/dashboard/signals/{id}`.

### T10 — `app/signals/routes.py` (MODIFY) — `POST /api/analyze/{symbol}`  ·  deps: T5, T4
- Add to `signals_router` (prefix `/api/signals`)? Task says `/api/analyze/{symbol}`. **Decision: new router `analyze_router = APIRouter(prefix="/api/analyze")` in same file; register in main.py.** Keeps path exactly `/api/analyze/{symbol}`.
- Handler:
  1. `sig = await generate_signal_single(symbol, with_ai=False)` (now fetches fin+foreign internally via T5).
  2. `df` — generator returns close etc. but not df; re-fetch via `fetch_ohlcv_safe(symbol)` OR have generator return `_df`. **Decision: `_build_one` already has `df`; add `"_df": df` to its return (transient) so analyze + scanner share it.** (scanner uses `cand["_df"]`, already has its own; harmless.)
  3. `chart_path = generate_chart(symbol, sig["_df"], sig, fin=sig.get("fin"), foreign_df=sig.get("_foreign_df"))`.
  4. `sig["chart_path"]=chart_path`; `sig_id = await save_signal_dict(sig)`; 
  5. Return JSON `{signal_id, chart_path, fin, snapshot}` (strip `_`-prefixed transient keys).
- Gate: `py_compile`.

### T11 — `app/main.py` (MODIFY)  ·  deps: T10
- Import + `app.include_router(analyze_router)`.
- Gate: `py_compile`; `/health` still 200.

---

## 3. Data Flow (ASCII, per-symbol deep path)

```
analyze/{symbol}  OR  scanner top-N
        │
        ▼
generate_signal_single / _build_one(symbol)
        │  fetch_ohlcv_safe(symbol) ───────────────▶ df (OHLCV, Yahoo)
        │  compute_features(df) ───────────────────▶ snap (technical)
        │  fetch_keystats(symbol)  [Stockbit] ─────▶ fin {21 fields}   (or {})
        │  fetch_foreign_flow(symbol) [Stockbit] ──▶ foreign_df         (or empty)
        │  snap.foreign_net_5d = Σ last5 net
        │  snap.trend_label (from MA stack)
        │  score_snapshot(snap) ───────────────────▶ score/action/reasons
        │  _levels(...) ───────────────────────────▶ entry/tp/sl/fib
        ▼
sig dict { ...levels, score, action, snapshot{...,fin,foreign_net_5d},
           fin, _df, _foreign_df }
        │
        ├─▶ generate_chart(symbol, _df, sig, fin, foreign_df)
        │        P1 price+MA+fib+cross+break
        │        P2 volume
        │        P3 RSI
        │        P4 MACD + foreign_net(twin)
        │        P5 PE/PBV band   (needs fin.eps_ttm/bvps)
        │        TABLE fundamentals + [+]/[!]/[=]  (needs fin)
        │   ───▶ PNG → chart_path
        │
        └─▶ save_signal_dict(sig)  (snapshot_json carries fin; _df/_foreign_df dropped)
                 │
                 ▼
        DB Signal row (chart_path, snapshot_json{...,fin})
                 │
                 ▼
   GET /dashboard/signals/{id} → parse snapshot.fin → HTML table + chart img
```

---

## 4. Edge Cases & Pitfalls (per component)

### stockbit_auth / fetch_stockbit
- **No token** (file missing, no cookie): `get_token()`→"" → fetch returns `{}`/empty. Pipeline must continue. ✅ already designed.
- **Symbol suffix**: Yahoo uses `BBCA.JK`; Stockbit uses bare `BBCA`. Strip `.JK`/`.JKT` and uppercase before Stockbit calls.
- **Expired token**: container can't refresh (host owns it). 401 → `{}`. Log once at WARNING, don't spam per symbol.
- **Keystats shape drift**: Stockbit nests/relabels fields; never index blindly. `_pick`/`_num` defensive, missing → None. Partial fin (some None) still renders table with blanks.
- **Rate limiting / timeout**: set httpx timeout ~10s. Top-N only (≤5 + on-demand), so volume is low — no throttle needed, but catch `httpx.HTTPError`/`TimeoutException`.
- **net_foreign sign**: confirm field name (`net_foreign` vs derive buy−sell). Handle both; derive if absent.

### indicators
- `trend_label` with short history (ma50/ma200 None) → SIDEWAYS, never crash on None compare.
- `foreign_net_5d` set by generator, not compute_features → `to_dict()` must emit it even when None.

### chart
- **eps_ttm ≤ 0 or None** (loss-making / missing): skip PE series, guard division. Same for `bvps`.
- **σ over tiny window**: if `<2` points or σ==0, skip band lines (avoid degenerate flat bands / div0).
- **foreign_df date misalignment** with df.index: reindex to df.index, `fillna(0)`; if zero overlap → skip foreign overlay.
- **Crossover detection** on NaN-leading MAs (min_periods): drop NaNs before sign-diff; guard empty.
- **Color change** P1: spec palette differs from current. Intentional per task — note in commit.
- **Table overflow**: long money strings → compact `T/B/M` formatting; fixed col widths; small font (7–8pt).
- **fin={} but chart requested**: panel 5 → "Fundamental N/A"; table omitted. Layout still 5 panels (GridSpec fixed) so no ragged figure.
- **Never raise**: per-panel try/except; top-level returns "".
- **Memory**: `plt.close("all")` in finally (already present) — keep, charts run in long-lived process.

### generator
- Stockbit fetch must be `await`-safe inside async `_build_one`. If using sync httpx, wrap in `run_in_executor` — but async httpx avoids that. Use async.
- Don't let fin fetch latency bloat scan: only top-N reach `_build_one` (verified — scanner scores inline, builds only top-N). Document so a future refactor doesn't accidentally route all candidates through `_build_one`.
- Transient `_df`/`_foreign_df` keys must NOT be JSON-serialized (DataFrames non-serializable). `save_signal_dict` only reads whitelisted keys → safe, but `snapshot` dict must not contain a DataFrame. Keep foreign data OUT of snapshot (only `foreign_net_5d` scalar in).

### dashboard / routes
- Existing path is `/dashboard/signals/{id}` (plural) — task wrote `/signal/` (singular). **Keep plural** to not break index link `:127`. Document deviation.
- Old signals (pre-feature) have `snapshot_json` without `fin` → table shows "Fundamental belum tersedia". No crash on `.get("fin", {})`.
- Regenerate route needs df: OHLCV cache (`load_ohlcv`) may lack enough rows → fallback `fetch_ohlcv_safe`. Re-fetch fin too.
- HTML injection: symbols are controlled (universe), but escape `summary`/reasons defensively if not already.

### api/analyze
- Invalid/unknown symbol → `generate_signal_single` returns None → HTTP 404 `{detail}`.
- Concurrent analyze of same symbol: each writes a new Signal row (acceptable; matches scanner behavior). No dedup required.
- Response must be JSON-clean: strip `_df`, `_foreign_df` before返回.

### main
- Router registration order irrelevant; ensure `analyze_router` imported from `app.signals.routes`.

---

## 5. Testing Checklist

Compile gate (run after each task and at end):
```
python3 -m py_compile \
  app/data/stockbit_auth.py app/data/fetch_stockbit.py \
  app/analytics/indicators.py app/analytics/fundamentals.py \
  app/signals/chart.py app/signals/generator.py \
  app/scanner.py app/dashboard/routes.py app/signals/routes.py app/main.py
```

Functional:
- [ ] `get_token()` returns non-empty when `STOCKBIT_ACCESS_FILE` present (or False cleanly when not).
- [ ] `fetch_keystats("BBCA")` returns dict with ≥ per/pbv/roe populated; bad symbol → `{}`.
- [ ] `fetch_foreign_flow("BBCA")` → DataFrame with `date,foreign_buy,foreign_sell,foreign_net`; bad → empty same-cols.
- [ ] `compute_features` sets `trend_label` ∈ {UPTREND,DOWNTREND,SIDEWAYS}; `to_dict()` includes new keys.
- [ ] `generate_chart(sym, df, sig, fin=None, foreign_df=None)` → valid PNG (backward compat, 5 panels, P5="N/A", no table).
- [ ] `generate_chart(... full fin + foreign_df)` → PNG with P5 bands + table + [+]/[!]/[=] + foreign overlay.
- [ ] `fundamentals.verdict("per", 10)` → `+` (below 14, lower-better); `verdict("roe", 20)` → `+`; `verdict("roe", 6)` → `!`; `verdict("per", 14.5)` → `=`.
- [ ] Scanner run (Top 20) completes, top-N charts are 5-panel, signals saved, no exceptions in log.
- [ ] Old signal detail page (no fin) renders without error.
- [ ] New signal detail page shows fundamental table + chart + levels.
- [ ] `POST /api/analyze/BBCA` → 200 `{signal_id, chart_path, fin, snapshot}`; chart file exists.
- [ ] `POST /api/analyze/ZZZZ` (bogus) → 404, no row written.
- [ ] Regenerate button updates chart_path, new PNG mtime.
- [ ] `/health` still 200; existing `/dashboard` index unchanged.
- [ ] No `_df`/`_foreign_df`/DataFrame leaked into `snapshot_json` (inspect a saved row).

Regression (must stay green):
- [ ] Full scan pipeline without Stockbit token configured → still produces signals + 4/5-panel charts (no fin).
- [ ] `compute_all` / legacy `score()` unaffected.

---

## Appendix A — File change summary

| File | Action | Task |
|---|---|---|
| app/data/stockbit_auth.py | NEW — token resolver + headers | T1 |
| app/data/fetch_stockbit.py | NEW — keystats + foreign flow (async httpx) | T2 |
| app/analytics/fundamentals.py | NEW — benchmark, verdict, fmt, fund_score, grade | T8 |
| app/analytics/indicators.py | MODIFY — +trend_label,+foreign_net_5d, to_dict | T3 |
| app/signals/chart.py | MODIFY — 5-panel + bands + table + header | T4 |
| app/signals/generator.py | MODIFY — Stockbit fetch, expose fin/_df/_foreign_df | T5 |
| app/scanner.py | MODIFY — pass fin/foreign_df to generate_chart | T6 |
| app/dashboard/routes.py | MODIFY — upgrade detail, +regenerate route | T7 |
| app/signals/routes.py | MODIFY — POST /api/analyze/{symbol} router | T10 |
| app/main.py | MODIFY — register analyze_router | T11 |

## Appendix B — Industry benchmark & verdict

```
BENCHMARK = {per:14.0, pbv:1.8, roe:14.0(%), roa:5.0(%), net_margin:10.0(%)}
in-line band = ±15%
PER, PBV  → lower-is-better:  value < bench*0.85 → [+], > bench*1.15 → [!], else [=]
ROE,ROA,NM→ higher-is-better: value > bench*1.15 → [+], < bench*0.85 → [!], else [=]
missing/None → "" (no tag)
```

## Appendix C — Key deviations from task spec (intentional)
1. Detail route kept at `/dashboard/signals/{id}` (plural, existing) not `/dashboard/signal/{id}`.
2. `ma5` NOT added — already present.
3. No new config field — reuse `STOCKBIT_ACCESS_FILE` + `STOCKBIT_SESSION_COOKIE` already in settings.
4. Verdict/format logic centralized in new `app/analytics/fundamentals.py` (shared chart + dashboard) — prevents drift; not in original file list.
5. Stockbit calls async (`httpx.AsyncClient`) rather than executor-wrapped requests — simpler in already-async generator.
6. `grade/tech/fund` sub-scores are documented heuristics (tech=signal score, fund=verdict tally), since repo has no separate fundamental scorer yet.
```
