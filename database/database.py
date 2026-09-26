"""
Database engine/session setup.

All DB access goes through ``get_session()`` / ``session_scope()`` defined
here. Nothing outside this module (and models.py) should import
SQLAlchemy's ``create_engine`` directly -- this keeps moving from SQLite
to a managed Postgres (e.g. Neon) a one-line change of ``DATABASE_URL``.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings
from database.models import Base

_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

# pool_pre_ping guards against a serverless/managed Postgres provider
# (Neon included) closing an idle connection server-side -- without it,
# the first query on a connection that went stale would fail outright
# instead of transparently reconnecting. It's a no-op for SQLite.
engine: Engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=not _is_sqlite,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create all tables if they do not already exist. Idempotent."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    """Return a new SQLAlchemy session. Caller is responsible for closing it."""
    return SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Commits on success, rolls back on any exception, and always closes the
    session. Prefer this over ``get_session()`` for anything that writes.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
