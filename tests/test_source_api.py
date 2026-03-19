"""Tests for manifest-based source API endpoints."""

import json
from unittest.mock import MagicMock
from sqlalchemy import text

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

ZSH_MANIFEST = {
    "name": "zsh",
    "version": "0.1.0",
    "display_name": "Zsh History",
    "db": {
        "table": "zsh_data",
        "columns": {
            "timestamp": "text not null",
            "command": "text not null default ''",
            "processed": "integer not null default 0",
        },
        "indexes": ["processed", "timestamp"],
    },
    "ui": {
        "icon": "terminal",
        "visible_columns": ["timestamp", "command"],
        "searchable_columns": ["command"],
    },
    "context": {"format": "[{timestamp}] [zsh]: {text}"},
    "config": {},
}


@pytest_asyncio.fixture
async def app_with_zsh_source(tmp_path):
    """Create a FastAPI app with zsh manifest source registered (own schema)."""
    import os
    import uuid as _uuid
    from sqlalchemy import create_engine as _ce
    from sqlalchemy.orm import sessionmaker as _sm
    from tests.conftest import TEST_PG_SYNC, TEST_PG_ASYNC, _TestDB

    # Own schema to avoid lock contention with shared schema
    schema = f"test_srcapi_{_uuid.uuid4().hex[:8]}"
    admin = _ce(TEST_PG_SYNC)
    with admin.connect() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
        c.commit()
    admin.dispose()

    sync_url = f"{TEST_PG_SYNC}?options=-csearch_path%3D{schema}"

    # Write manifest to a temp dir
    zsh_dir = tmp_path / "sources" / "zsh"
    zsh_dir.mkdir(parents=True)
    (zsh_dir / "manifest.json").write_text(json.dumps(ZSH_MANIFEST))

    os.environ["SOURCES_DIR"] = str(tmp_path / "sources")

    from engine.etl.sources.manifest_registry import (
        ManifestRegistry, create_table_for_manifest, load_manifest_data,
    )
    from engine.storage.models import Base

    # Create ORM tables + manifest table in own schema
    schema_engine = _ce(sync_url)
    Base.metadata.create_all(schema_engine)
    session = _sm(bind=schema_engine)()
    manifest = load_manifest_data(zsh_dir)
    create_table_for_manifest(session, manifest)
    session.close()
    schema_engine.dispose()

    registry = ManifestRegistry()
    registry.register(manifest)

    from fastapi import FastAPI
    from engine.api.routes import router

    app = FastAPI()
    app.include_router(router)

    settings = MagicMock()
    settings.database_url_sync = sync_url

    db = _TestDB(TEST_PG_ASYNC, schema)
    await db.connect()
    app.state.db = db
    app.state.manifest_registry = registry
    app.state.settings = settings

    yield app

    await db.close()
    os.environ.pop("SOURCES_DIR", None)

    # Drop entire schema
    admin = _ce(TEST_PG_SYNC)
    with admin.connect() as c:
        c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        c.commit()
    admin.dispose()


@pytest_asyncio.fixture
async def client(app_with_zsh_source):
    transport = ASGITransport(app=app_with_zsh_source)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSourcesAPI:
    async def test_list_sources(self, client):
        resp = await client.get("/engine/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sources"]) == 1
        assert data["sources"][0]["name"] == "zsh"
        assert data["sources"][0]["display_name"] == "Zsh History"

    async def test_ingest_and_query(self, client):
        # Ingest
        resp = await client.post("/ingest/zsh", json={
            "timestamp": "2026-01-01T00:00:00Z",
            "command": "git status",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] > 0

        # Query
        resp = await client.get("/sources/zsh/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["records"][0]["command"] == "git status"

    async def test_ingest_unknown_source(self, client):
        resp = await client.post("/ingest/nonexistent", json={"data": "test"})
        # The endpoint returns error for unknown sources
        data = resp.json()
        assert "error" in str(data) or "Unknown source" in str(data)

    async def test_query_unknown_source(self, client):
        resp = await client.get("/sources/nonexistent/data")
        data = resp.json()
        assert "error" in str(data) or "Unknown source" in str(data)

    async def test_query_with_search(self, client):
        await client.post("/ingest/zsh", json={"timestamp": "t1", "command": "git status"})
        await client.post("/ingest/zsh", json={"timestamp": "t2", "command": "npm install"})
        await client.post("/ingest/zsh", json={"timestamp": "t3", "command": "git log"})

        resp = await client.get("/sources/zsh/data", params={"search": "git"})
        data = resp.json()
        assert data["total"] == 2

    async def test_query_pagination(self, client):
        for i in range(10):
            await client.post("/ingest/zsh", json={"timestamp": f"t{i}", "command": f"cmd_{i}"})

        resp = await client.get("/sources/zsh/data", params={"limit": 3, "offset": 0})
        data = resp.json()
        assert data["total"] == 10
        assert len(data["records"]) == 3
