import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
# Postgres/PostGIS when DATABASE_URL is set (see database/docker-compose.yml); otherwise a local SQLite file.
DATABASE_URL = os.getenv('DATABASE_URL') or f"sqlite:///{ROOT / 'data' / 'tourist_safety.db'}"
# Hosts hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg driver named explicitly.
for prefix in ('postgres://', 'postgresql://'):
    if DATABASE_URL.startswith(prefix):
        DATABASE_URL = 'postgresql+psycopg://' + DATABASE_URL[len(prefix):]
(ROOT / 'data').mkdir(exist_ok=True)
connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
pool_args = {} if DATABASE_URL.startswith('sqlite') else dict(
    pool_size=int(os.getenv('DB_POOL_SIZE', '10')), max_overflow=int(os.getenv('DB_MAX_OVERFLOW', '20')), pool_recycle=1800)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args, **pool_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# create_all() never adds indexes to tables that already exist, so these are applied idempotently at startup.
INDEXES = [
    'CREATE INDEX IF NOT EXISTS ix_tloc_tourist_time ON tourist_locations (tourist_id, recorded_at)',
    'CREATE INDEX IF NOT EXISTS ix_risk_tourist_time ON risk_assessments (tourist_id, assessed_at)',
    'CREATE INDEX IF NOT EXISTS ix_incident_tourist_status ON incidents (tourist_id, status)',
    'CREATE INDEX IF NOT EXISTS ix_ledger_type_ref ON ledger_blocks (block_type, ref)',
]


def ensure_indexes():
    from sqlalchemy import text
    with engine.begin() as c:
        for stmt in INDEXES:
            c.execute(text(stmt))
