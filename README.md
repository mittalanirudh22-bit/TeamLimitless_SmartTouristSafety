# Team Limitless — Smart Tourist Safety Platform

Location-agnostic tourist safety MVP. Bhopal is the pilot; the core code is designed to work with other locations by changing configuration and normalized datasets.

Pipeline:
Real GPS -> feature engineering -> Isolation Forest movement anomaly -> GIS/context signals -> transparent risk engine -> FastAPI -> React dashboard -> incident response.

Important: GeoLife has real GPS trajectories but no reliable emergency/crime labels. The anomaly model detects unusual movement, not danger or crime. SOS/incident scenarios are controlled demo inputs.

## Quick start

1. Copy `.env.example` to `.env`.
2. Start PostgreSQL/PostGIS:
   `cd database && docker compose up -d`
3. Install Python dependencies:
   `pip install -r requirements.txt`
4. Put extracted GeoLife under `data/raw/geolife/`.
5. Run:
   `python scripts/parse_geolife.py`
   `python scripts/feature_engineering.py`
   `python ml/train_anomaly.py`
6. Start API:
   `uvicorn backend.main:app --reload`
7. Start frontend:
   `cd frontend && npm install && npm run dev`

For another location:
`python scripts/setup_location.py --city Jaipur --state Rajasthan --country India`

Risk weights are configured in each location YAML and are an MVP decision-support score, not a calibrated probability.

## One-command local run (no Docker/Postgres needed)
```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/generate_datasets.py   # synthetic GeoLife-format data + context (skip if you have real GeoLife)
.venv/bin/python scripts/parse_geolife.py && .venv/bin/python scripts/feature_engineering.py && .venv/bin/python ml/train_anomaly.py
(cd frontend && npm install && npm run build)
.venv/bin/uvicorn backend.main:app --port 8000     # dashboard + API at http://localhost:8000
```
The API uses SQLite by default; set `DATABASE_URL` to the PostGIS URL to use Postgres (tables are created on startup).
Deploy anywhere that runs Docker: `docker build -t limitless . && docker run -p 8000:8000 limitless` (see `Dockerfile`).

## Traveller registration & tracking
- `/` — travellers register (with explicit location-tracking consent), receive a blockchain ID (`TLB-XXXX-XXXX-XXXX-XXXX`) and a private tracking login stored in their browser, then opt in to GPS tracking. Anyone can verify an ID on the same page (`GET /api/verify/{id}`).
- `/#/ops` — operator dashboard (live map, incidents, ledger). Protected by the `OPS_TOKEN` env var when set; open when unset (local dev).
- The "blockchain" is a private SHA-256 hash chain in the database (`backend/ledger.py`): registrations, tracking start/stop and incident events are chained; only salted hashes are stored, never personal data. It detects silent edits but is not a public chain.
- Browser GPS needs HTTPS (Render provides it) or localhost. "Use demo movement" simulates a walk for testing.

## Performance & load testing
`python scripts/loadtest.py --travellers 100 --fixes 30 --concurrency 48` registers test travellers, streams GPS fixes, then waits for the ingest workers to drain and reports end-to-end throughput. Run it only against a local or throwaway deployment, with `REGISTER_LIMIT_PER_HOUR=100000` on the server. `python -m pytest tests` runs the regression suite (`pip install -r requirements-dev.txt`).

**Reading the numbers honestly.** One Python client process tops out near ~400 req/s on a laptop even against `/health`, so single-client results measure the client as much as the server. Run several clients at once. Local reference (laptop, SQLite, 1 uvicorn worker, 4 client processes sharing the same CPU): ~900 fixes/s accepted and fully processed, 0 errors. Postgres numbers (network round trips) have not been measured.

What makes it fast:
* **Stage 1** - vectorised IsolationForest scorer (`ml/fast_iforest.py`, exact match to sklearn, ~55x faster per call), cached geofences/crime context, a `tourist_state` table so scoring and dashboards read one row per tourist, indexes.
* **Stage 2** - `POST /api/travellers/me/location` validates and enqueues (HTTP 202); sharded workers (`backend/ingest.py`) score in batches: one state read, one model call, one commit per batch. Batch processor alone: ~1.3k fixes/s at batch size 1, ~6k at 100, ~13k at 3000 (SQLite). A poison fix is isolated and dropped; duplicates and late fixes are idempotent; the API sheds load with 503 + `Retry-After` past `INGEST_MAX_QUEUE`. Dashboard polls deltas (`/api/tourists?since=`). History is purged after `RETENTION_DAYS` (default 30; `0` disables). Risk history is sampled (level change / SOS / each minute); the full-rate value lives in `tourist_state`.

**Scaling out (needs Postgres + Redis).** Set `REDIS_URL` and fixes flow through Redis Streams (consumer groups, ack after commit = at-least-once, dead-consumer messages are re-claimed). Run extra consumers with `python -m backend.worker --name w1` and set `INGEST_EMBEDDED_WORKERS=0` on web instances that should only enqueue. Shared registration rate limiting also moves to Redis. Without `REDIS_URL` everything runs in-process (the Render free-tier setup). `WEB_CONCURRENCY>1` requires Postgres (cross-process ledger lock) and breaks the single-process demo replay. Mind Postgres `max_connections`: each process uses up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` (default 20+40).
