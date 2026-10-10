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
`python scripts/loadtest.py --travellers 100 --fixes 30 --concurrency 64` registers test travellers and streams GPS fixes (run it only against a local or throwaway deployment; set `REGISTER_LIMIT_PER_HOUR=100000` on the server). `python -m pytest tests` runs the regression suite (`pip install -r requirements-dev.txt`).

Measured locally (1 worker, SQLite, 64 concurrent clients): **97 -> ~670 fixes/s**, p50 207 -> ~88 ms. What changed: a vectorised IsolationForest scorer (`ml/fast_iforest.py`, exact match to sklearn, ~55x faster per call), cached geofences/crime context, a `tourist_state` table so scoring and dashboards read one row per tourist instead of scanning history, and indexes. Postgres numbers will differ (network round trips) and have not been measured yet.
