# MAI-IDX-Signal

IDX (Indonesian Stock Exchange) signal scanner: deterministic technical scoring
+ Claude reasoning + Telegram/WhatsApp delivery + web dashboard + performance
tracking. Deployed via Docker on Synology Container Manager.

## Architecture

```text
Data Sources (Yahoo / Stockbit)
  -> Fetcher / Normalizer        app/data/
  -> Indicators                  app/analytics/indicators.py
  -> Deterministic Scoring       app/analytics/scoring.py
  -> Claude Reasoning            app/ai/
  -> Signal Generator            app/signals/generator.py
  -> Delivery (Telegram/WA/Web)  app/bots/, app/dashboard/
  -> Performance Tracker         app/signals/tracker.py
  -> Scheduler (APScheduler)     app/scheduler/jobs.py
```

- **Backend**: Python 3.12, FastAPI, Uvicorn
- **DB**: SQLite (async via aiosqlite + SQLAlchemy)
- **Analytics**: pandas, numpy, matplotlib
- **AI**: Claude via Anthropic-compatible endpoint (9Router), strict JSON output
- **Deploy**: Docker Compose on Synology, GHCR image, GitHub Actions CI/CD

## Setup (local)

```bash
uv venv .venv && . .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env   # fill in tokens
python -m pytest tests/ -v
uvicorn app.main:app --reload
```

Scan once from the CLI:

```bash
python scripts/scan_once.py
```

Health check: `GET http://localhost:8000/health` → `{"status":"ok","version":"0.1.0"}`

## API

- `GET /health` — liveness
- `GET /signals/{symbol}` — single signal
- `GET /scan?top_n=5&limit=10` — scan universe, top signals
- `GET /dashboard/` — latest signals (HTML)
- `GET /dashboard/performance` — win rate / avg PnL
- `GET /dashboard/symbols/{ticker}` — per-symbol history

## Docker deploy

Image: `ghcr.io/merkuriusanthony/mai-idx-signal:latest`, app port `8000`,
NAS external port `7843`.

```bash
docker compose pull
docker compose up -d
curl http://<nas-ip>:7843/health
```

On Synology the compose file lives at
`/volume1/docker/mai-idx-signal/docker-compose.yml` with data volume
`./data:/app/data`.

### CI/CD

`.github/workflows/docker.yml` runs on push to `main`:
1. **test** — pytest
2. **build-push** — build image, push to GHCR
3. **deploy** — SSH to NAS (`100.98.225.116`) via `SSH_PRIVATE_KEY`,
   `docker compose pull && up -d`

Required GitHub secrets: `SSH_PRIVATE_KEY`, `SSH_USER`.

## Bot commands (Telegram)

The bot replies `Sedang analisa...` before long analysis.

- `/signal TICKER` — full signal for a ticker (entry/TP/SL + AI reasoning)
- `/scan` — scan universe, return top 5
- `/why TICKER` — reasoning breakdown
- `/track` — open positions / tracking summary
- `/health` — liveness

## Scoring labels

`BUY` (≥75) · `WATCH` (≥60) · `HOLD` (≥45) · `AVOID` (≥30) · `DANGER` (<30)

## Scheduler (WIB = UTC+7)

`08:30` premarket · `09:15` opening · every `5min` 09:00–16:00 intraday ·
`13:00` midday · `15:45` closing · `16:30` EOD report.

## Disclaimer

Signals are informational only, not investment advice. Always use risk
management.
