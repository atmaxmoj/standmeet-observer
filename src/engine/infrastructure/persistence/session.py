"""Session + time utilities for cross-database compatibility."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine as _sa_create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.config import Settings

_factory_cache: dict[str, sessionmaker] = {}


def get_session(conn_or_url) -> Session:
    """Get a SQLAlchemy Session.

    Accepts:
    - str (URL): creates engine from URL
    - other: uses database_url_sync from settings
    """
    if isinstance(conn_or_url, str):
        url = conn_or_url
    else:
        # psycopg or other: use settings URL
        url = Settings().database_url_sync

    if url not in _factory_cache:
        engine = _sa_create_engine(url)
        _factory_cache[url] = sessionmaker(bind=engine)
    return _factory_cache[url]()


def ago(days: int = 0, hours: int = 0) -> str:
    """Return ISO timestamp for N days/hours ago. Cross-database compatible."""
    dt = datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    return dt.isoformat()
