"""
Database engine/session setup. Swapping local -> cloud Postgres later
is just a change to DATABASE_URL in .env — nothing here changes.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from agentcare.config import DATABASE_URL

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=True, autocommit=False, future=True)
Base = declarative_base()


def init_db():
    """Create all tables if they don't exist. Safe to call every startup."""
    import agentcare.models  # noqa: F401  (ensures models are registered on Base)
    Base.metadata.create_all(bind=engine)


def get_session():
    """Yield a new session; caller is responsible for closing it."""
    return SessionLocal()
