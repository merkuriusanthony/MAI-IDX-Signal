# Phase 4 — Production Hardening + Public Product

## Goals

Fix endpoint issues found after Phase 3 and harden MAI-IDX-Signal for public/product use.

## Group A — Endpoint/status fixes

1. Add `/api/status` endpoint.
2. Response should include:
   - status
   - version
   - database connectivity
   - table presence for key tables: signals, scan_runs, scan_candidates, backtest_runs, backtest_results, users
   - latest signal count / latest scan metadata if cheap
   - scheduler enabled flag if available
3. Keep existing `/health` and `/api/health` unchanged.
4. Add tests for `/api/status`.

## Group B — Backtest API no-timeout

1. Make `/api/backtest` fast and non-blocking by creating a queued/background run.
2. Add `BacktestRun.status` lifecycle: queued/running/completed/failed.
3. Add endpoints:
   - `GET /api/backtest/runs` latest runs
   - `GET /api/backtest/runs/{run_id}` run detail + limited results
   - `POST /api/backtest/run` alias if useful for dashboard/API consistency
4. Dashboard `/dashboard/backtest` must not crash if tables missing or no runs.
5. Add tests for backtest creation and run listing.

## Group C — Dashboard ops page

1. Add `/dashboard/status` page with:
   - app version
   - DB status
   - table status
   - latest scan
   - latest signals
   - useful links to dashboard/performance/sectors/backtest/admin/member
2. Add link to status page from main dashboard.
3. Add tests for `/dashboard/status`.

## Group D — Public product readiness

1. Landing page should link to dashboard/status/member/admin/backtest.
2. README or docs update with valid endpoints:
   - `/health`
   - `/api/health`
   - `/api/status`
   - `/api/signals/latest`
   - `/api/backtest/runs`
   - `/dashboard/status`
3. Version bump to `0.6.0`.
4. Do not configure Cloudflare DNS/tunnel from code. Document required mapping: `mai.claireantonia.id -> NAS:7843`.

## Constraints

- Use existing FastAPI + SQLAlchemy async style.
- Preserve existing behavior and tests.
- Do not remove existing endpoints.
- Prefer small commits per group.
- Run `uv run pytest -q` after changes.
- Do not deploy from Claude Code. Hermes will deploy after verifying.
