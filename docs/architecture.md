# Architecture
Data ingestion -> normalization -> mobility features -> unsupervised anomaly detection -> GIS/geofences -> contextual signals -> risk engine -> incident response -> API -> frontend.

Location-specific configuration lives under `locations/<slug>/`. Avoid city-specific conditionals in the core engine.
