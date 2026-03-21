"""Shared fixtures for engine tests.

Single schema per session, TRUNCATE between tests. No per-test DDL = no lock contention.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from engine.infrastructure.persistence.db import DB
from engine.infrastructure.persistence.models import Base

import os

_pg_host = os.environ.get("TEST_PG_HOST", "localhost")
_pg_port = os.environ.get("TEST_PG_PORT", "15432")
_pg_db = os.environ.get("TEST_PG_DB", "observer")
TEST_PG_SYNC = f"postgresql+psycopg://observer:observer@{_pg_host}:{_pg_port}/{_pg_db}"
TEST_PG_ASYNC = f"postgresql+asyncpg://observer:observer@{_pg_host}:{_pg_port}/{_pg_db}"

_SCHEMA = f"test_{uuid.uuid4().hex[:8]}"
_SYNC_URL = f"{TEST_PG_SYNC}?options=-csearch_path%3D{_SCHEMA}"

# Session-scoped sync engine — reused across all tests
_engine = None
_truncate_sql = None


@pytest.fixture(scope="session", autouse=True)
def _init_schema():
    """Create schema + tables once for the entire session."""
    global _engine, _truncate_sql

    admin = create_engine(TEST_PG_SYNC)
    with admin.connect() as c:
        c.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
        c.commit()
    admin.dispose()

    _engine = create_engine(_SYNC_URL, pool_size=5, max_overflow=5)
    Base.metadata.create_all(_engine)

    tables = list(Base.metadata.tables.keys())
    _truncate_sql = f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE" if tables else None

    yield

    _engine.dispose()
    admin = create_engine(TEST_PG_SYNC)
    with admin.connect() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        c.commit()
    admin.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    """TRUNCATE all tables after each test."""
    yield
    if _truncate_sql and _engine:
        with _engine.connect() as c:
            c.execute(text(_truncate_sql))
            c.commit()


@pytest.fixture
def _test_schema():
    """Expose schema name for tests that need it."""
    return _SCHEMA


class _TestDB(DB):
    """Async DB targeting the test schema."""

    def __init__(self, url: str, schema: str):
        super().__init__(url)
        self._schema = schema

    async def connect(self):
        self._engine = create_async_engine(
            self.url, echo=False,
            connect_args={"server_settings": {"search_path": self._schema}},
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine, expire_on_commit=False,
        )


@pytest_asyncio.fixture
async def db():
    """Async DB for each test."""
    database = _TestDB(TEST_PG_ASYNC, _SCHEMA)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def sync_session():
    """Sync session using the shared engine."""
    session = sessionmaker(bind=_engine)()
    yield session
    session.close()
