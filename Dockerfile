FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY ml ml
COPY locations locations
COPY scripts scripts
# Rebuild the (synthetic) datasets and retrain the model at image build time; seeded, so reproducible.
RUN mkdir -p data/processed \
 && python scripts/generate_datasets.py \
 && python scripts/parse_geolife.py \
 && python scripts/feature_engineering.py \
 && python ml/train_anomaly.py \
 && rm -rf data/raw data/processed/geolife_points.csv data/processed/mobility_features.csv
COPY --from=web /web/dist frontend/dist
ENV PORT=8000
# WEB_CONCURRENCY>1 needs Postgres (ledger lock) and disables the single-process demo replay.
CMD ["sh","-c","uvicorn backend.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY:-1}"]
