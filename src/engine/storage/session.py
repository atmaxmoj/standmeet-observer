"""Session + time utilities for cross-database compatibility."""

import sqlite3
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.storage.models import Base

_cache: dict[int, sessionmaker] = {}


def get_session(conn: sqlite3.Connection) -> Session:
    """Wrap a raw sqlite3.Connection in a SQLAlchemy Session.

    Caches the engine per connection id to avoid recreating on every call.
    """
    conn_id = id(conn)
    if conn_id not in _cache:
        engine = create_engine("sqlite://", creator=lambda: conn)
        Base.metadata.create_all(engine)
        _cache[conn_id] = sessionmaker(bind=engine)
    return _cache[conn_id]()


def ago(days: int = 0, hours: int = 0) -> str:
    """Return ISO timestamp for N days/hours ago. Cross-database compatible."""
    dt = datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    return dt.isoformat()
