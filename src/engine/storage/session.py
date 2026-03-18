"""Session + time utilities for cross-database compatibility."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.storage.models import Base

_cache: dict[int, sessionmaker] = {}


def get_session(conn) -> Session:
    """Wrap a raw DB connection in a SQLAlchemy Session.

    Supports sqlite3.Connection and psycopg.Connection.
    Caches the engine per connection id.
    """
    import sqlite3
    conn_id = id(conn)
    if conn_id not in _cache:
        if isinstance(conn, sqlite3.Connection):
            engine = create_engine("sqlite://", creator=lambda: conn)
        else:
            # psycopg or other DBAPI connection
            engine = create_engine("postgresql+psycopg://", creator=lambda: conn)
        Base.metadata.create_all(engine)
        _cache[conn_id] = sessionmaker(bind=engine)
    return _cache[conn_id]()


def ago(days: int = 0, hours: int = 0) -> str:
    """Return ISO timestamp for N days/hours ago. Cross-database compatible."""
    dt = datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    return dt.isoformat()
