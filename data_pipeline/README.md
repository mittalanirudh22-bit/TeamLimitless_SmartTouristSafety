# Data pipeline
External data is normalized to stable internal schemas so the core engine can work across locations.

GPS: user_id, trajectory_id, timestamp, latitude, longitude, altitude
Tourism: location, year, domestic_visitors, foreign_visitors
Safety: location, year, crime_category, crime_count
POI: poi_id, name, category, latitude, longitude, geometry
