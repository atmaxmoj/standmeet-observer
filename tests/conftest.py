"""Shared fixtures for engine tests."""

import asyncio
import pytest
import pytest_asyncio

from engine.storage.db import DB


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db(tmp_path):
    """Create a fresh in-memory-like DB for each test."""
    db_path = str(tmp_path / "test.db")
    database = DB(f"sqlite+aiosqlite:///{db_path}")
    await database.connect()
    yield database
    await database.close()
