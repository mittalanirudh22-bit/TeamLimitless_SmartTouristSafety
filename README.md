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
