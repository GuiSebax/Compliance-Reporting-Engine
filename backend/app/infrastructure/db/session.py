"""Database engine/session wiring.

``echo`` and pool sizing are intentionally not exposed as public knobs
beyond the connection string — this is a reporting engine, not a
high-throughput OLTP service, so a single sensible pool configuration is
enough and avoids a class of misconfiguration bugs.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _make_engine() -> Engine:
    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        # Needed so the same SQLite connection can be shared across the
        # request's dependency-injected session in a single-threaded test
        # server; production always uses Postgres.
        connect_args["check_same_thread"] = False
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
