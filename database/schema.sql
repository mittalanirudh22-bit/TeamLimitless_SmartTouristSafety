CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS locations (
 id SERIAL PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 state TEXT, country TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tourists (
 tourist_id TEXT PRIMARY KEY, location_slug TEXT REFERENCES locations(slug),
 display_name TEXT, status TEXT DEFAULT 'ACTIVE', created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tourist_locations (
 id BIGSERIAL PRIMARY KEY, tourist_id TEXT REFERENCES tourists(tourist_id),
 recorded_at TIMESTAMPTZ NOT NULL, latitude DOUBLE PRECISION NOT NULL,
 longitude DOUBLE PRECISION NOT NULL, speed_kmh DOUBLE PRECISION,
 acceleration_kmh_s DOUBLE PRECISION, direction_change_deg DOUBLE PRECISION,
 inactivity_seconds DOUBLE PRECISION,
 geom GEOMETRY(Point,4326) GENERATED ALWAYS AS
 (ST_SetSRID(ST_MakePoint(longitude,latitude),4326)) STORED
);
CREATE INDEX IF NOT EXISTS idx_tourist_locations_geom
ON tourist_locations USING GIST (geom);

CREATE TABLE IF NOT EXISTS geofences (
 id SERIAL PRIMARY KEY, location_slug TEXT REFERENCES locations(slug),
 name TEXT NOT NULL, category TEXT, risk_level DOUBLE PRECISION DEFAULT 0,
 description TEXT, geom GEOMETRY(Polygon,4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_geofences_geom ON geofences USING GIST (geom);

CREATE TABLE IF NOT EXISTS tourism_context (
 id SERIAL PRIMARY KEY, location_slug TEXT REFERENCES locations(slug), year INT,
 domestic_visitors BIGINT, foreign_visitors BIGINT, source TEXT
);

CREATE TABLE IF NOT EXISTS safety_context (
 id SERIAL PRIMARY KEY, location_slug TEXT REFERENCES locations(slug), year INT,
 crime_category TEXT, crime_count BIGINT, source TEXT
);

CREATE TABLE IF NOT EXISTS risk_assessments (
 id BIGSERIAL PRIMARY KEY, tourist_id TEXT REFERENCES tourists(tourist_id),
 assessed_at TIMESTAMPTZ DEFAULT now(), movement_anomaly DOUBLE PRECISION DEFAULT 0,
 geofence_risk DOUBLE PRECISION DEFAULT 0, route_deviation DOUBLE PRECISION DEFAULT 0,
 inactivity DOUBLE PRECISION DEFAULT 0, historical_context DOUBLE PRECISION DEFAULT 0,
 night_flag DOUBLE PRECISION DEFAULT 0, sos DOUBLE PRECISION DEFAULT 0,
 risk_score DOUBLE PRECISION NOT NULL, risk_level TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
 id BIGSERIAL PRIMARY KEY, tourist_id TEXT REFERENCES tourists(tourist_id),
 incident_type TEXT NOT NULL, severity TEXT, latitude DOUBLE PRECISION,
 longitude DOUBLE PRECISION, status TEXT DEFAULT 'OPEN', description TEXT,
 created_at TIMESTAMPTZ DEFAULT now(), resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS incident_audit (
 id BIGSERIAL PRIMARY KEY, incident_id BIGINT REFERENCES incidents(id),
 action TEXT NOT NULL, actor TEXT, details JSONB, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE OR REPLACE VIEW latest_tourist_risk AS
SELECT DISTINCT ON (tourist_id) tourist_id, assessed_at, risk_score, risk_level
FROM risk_assessments ORDER BY tourist_id, assessed_at DESC;
