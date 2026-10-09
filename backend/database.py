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
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
