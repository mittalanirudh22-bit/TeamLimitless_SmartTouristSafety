"""Portable ORM schema (SQLite or Postgres). database/schema.sql remains the PostGIS-native variant."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()
now = lambda: datetime.now(timezone.utc)
PK = BigInteger().with_variant(Integer, 'sqlite')


class Location(Base):
    __tablename__ = 'locations'
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    state = Column(String)
    country = Column(String, nullable=False)


class Tourist(Base):
    __tablename__ = 'tourists'
    tourist_id = Column(String, primary_key=True)
    location_slug = Column(String, ForeignKey('locations.slug'))
    display_name = Column(String)
    status = Column(String, default='ACTIVE')
    dest_lat = Column(Float)
    dest_lon = Column(Float)
    start_lat = Column(Float)
    start_lon = Column(Float)
    created_at = Column(DateTime(timezone=True), default=now)


class TouristLocation(Base):
    __tablename__ = 'tourist_locations'
    id = Column(PK, primary_key=True, autoincrement=True)
    tourist_id = Column(String, ForeignKey('tourists.tourist_id'), index=True)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    speed_kmh = Column(Float)
    acceleration_kmh_s = Column(Float)
    direction_change_deg = Column(Float)
    inactivity_seconds = Column(Float)


class Geofence(Base):
    __tablename__ = 'geofences'
    id = Column(Integer, primary_key=True)
    location_slug = Column(String, ForeignKey('locations.slug'))
    name = Column(String, nullable=False)
    category = Column(String)
    risk_level = Column(Float, default=0)
    description = Column(Text)
    geojson = Column(JSON, nullable=False)


class TourismContext(Base):
    __tablename__ = 'tourism_context'
    id = Column(Integer, primary_key=True)
    location_slug = Column(String)
    year = Column(Integer)
    domestic_visitors = Column(BigInteger)
    foreign_visitors = Column(BigInteger)
    source = Column(String)


class SafetyContext(Base):
    __tablename__ = 'safety_context'
    id = Column(Integer, primary_key=True)
    location_slug = Column(String)
    year = Column(Integer)
    crime_category = Column(String)
    crime_count = Column(BigInteger)
    source = Column(String)


class RiskAssessment(Base):
    __tablename__ = 'risk_assessments'
    id = Column(PK, primary_key=True, autoincrement=True)
    tourist_id = Column(String, ForeignKey('tourists.tourist_id'), index=True)
    assessed_at = Column(DateTime(timezone=True), default=now)
    movement_anomaly = Column(Float, default=0)
    geofence_risk = Column(Float, default=0)
    route_deviation = Column(Float, default=0)
    inactivity = Column(Float, default=0)
    historical_context = Column(Float, default=0)
    night_flag = Column(Float, default=0)
    sos = Column(Float, default=0)
    risk_score = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False)


class Incident(Base):
    __tablename__ = 'incidents'
    id = Column(PK, primary_key=True, autoincrement=True)
    tourist_id = Column(String, ForeignKey('tourists.tourist_id'))
    incident_type = Column(String, nullable=False)
    severity = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    status = Column(String, default='OPEN')
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now)
    resolved_at = Column(DateTime(timezone=True))


class IncidentAudit(Base):
    __tablename__ = 'incident_audit'
    id = Column(PK, primary_key=True, autoincrement=True)
    incident_id = Column(BigInteger().with_variant(Integer, 'sqlite'), ForeignKey('incidents.id'))
    action = Column(String, nullable=False)
    actor = Column(String)
    details = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=now)


class Registration(Base):
    """Traveller profile. PII lives here (and only here); the ledger stores hashes."""
    __tablename__ = 'registrations'
    tourist_id = Column(String, ForeignKey('tourists.tourist_id'), primary_key=True)
    full_name = Column(String, nullable=False)
    nationality = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String)
    emergency_name = Column(String, nullable=False)
    emergency_phone = Column(String, nullable=False)
    blockchain_id = Column(String, unique=True, index=True, nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    salt = Column(String, nullable=False)
    consent_at = Column(DateTime(timezone=True), nullable=False)
    registered_at = Column(DateTime(timezone=True), default=now)


class LedgerBlock(Base):
    """Append-only hash chain. hash = sha256(idx|ts|block_type|ref|payload_hash|prev_hash)."""
    __tablename__ = 'ledger_blocks'
    idx = Column(Integer, primary_key=True, autoincrement=False)
    ts = Column(String, nullable=False)
    block_type = Column(String, nullable=False)
    ref = Column(String, index=True)
    payload_hash = Column(String, nullable=False)
    prev_hash = Column(String, nullable=False)
    hash = Column(String, unique=True, nullable=False)
