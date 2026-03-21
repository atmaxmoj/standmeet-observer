"""Tests for ManifestRegistry — manifest loading, table creation, ingest, query."""

import json
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from engine.infrastructure.etl.sources.manifest_registry import (
    ManifestCaptureSource,
    ManifestRegistry,
    load_manifest_data,
    scan_sources_dir,
    create_table_for_manifest,
    insert_record,
    query_records,
)
from engine.domain.observation.entity import Frame


ZSH_MANIFEST = {
    "name": "zsh",
    "version": "0.1.0",
    "display_name": "Zsh History",
    "description": "Shell commands from zsh",
    "author": "builtin",
    "platform": ["darwin"],
    "entrypoint": "zsh_source:ZshSource",
    "events": {"shell_command": {"label": "Shell Command", "color": "green"}},
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
        "detail_columns": [],
    },
    "context": {
        "description": "Shell commands from zsh",
        "format": "[{timestamp}] [zsh]: {text}",
    },
    "gc": {"prompt": "Purge old zsh data", "retention_days_default": 30},
    "config": {"interval_seconds": {"type": "number", "default": 3, "label": "Interval"}},
}


@pytest.fixture
def zsh_manifest():
    return load_manifest_data(_write_manifest(ZSH_MANIFEST))


@pytest.fixture
def db_session():
    """Own isolated schema for manifest tests (creates dynamic tables)."""
    from tests.conftest import TEST_PG_SYNC
    schema = f"test_manifest_{uuid.uuid4().hex[:8]}"
    admin = create_engine(TEST_PG_SYNC)
    with admin.connect() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
        c.commit()
    admin.dispose()

    engine = create_engine(f"{TEST_PG_SYNC}?options=-csearch_path%3D{schema}")
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()

    admin = create_engine(TEST_PG_SYNC)
    with admin.connect() as c:
        c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        c.commit()
    admin.dispose()


def _write_manifest(data: dict) -> Path:
    d = tempfile.mkdtemp()
    p = Path(d) / "manifest.json"
    p.write_text(json.dumps(data))
    return p


class TestLoadManifestData:
    def test_loads_all_fields(self):
        m = load_manifest_data(_write_manifest(ZSH_MANIFEST))
        assert m.name == "zsh"
        assert m.display_name == "Zsh History"
        assert m.db_table == "zsh_data"
        assert "timestamp" in m.db_columns
        assert "command" in m.db_columns
        assert m.db_indexes == ["processed", "timestamp"]
        assert m.context_format == "[{timestamp}] [zsh]: {text}"

    def test_loads_from_directory(self, tmp_path):
        (tmp_path / "manifest.json").write_text(json.dumps(ZSH_MANIFEST))
        m = load_manifest_data(tmp_path)
        assert m.name == "zsh"

    def test_preserves_raw(self):
        m = load_manifest_data(_write_manifest(ZSH_MANIFEST))
        assert m.raw["name"] == "zsh"
        assert m.raw["db"]["table"] == "zsh_data"


class TestScanSourcesDir:
    def test_finds_manifests(self, tmp_path):
        zsh_dir = tmp_path / "zsh"
        zsh_dir.mkdir()
        (zsh_dir / "manifest.json").write_text(json.dumps(ZSH_MANIFEST))

        bash_dir = tmp_path / "bash"
        bash_dir.mkdir()
        (bash_dir / "manifest.json").write_text(json.dumps({
            "name": "bash", "db": {"table": "bash_data", "columns": {"timestamp": "text not null"}}
        }))

        manifests = scan_sources_dir(tmp_path)
        assert len(manifests) == 2
        names = {m.name for m in manifests}
        assert names == {"zsh", "bash"}

    def test_skips_dirs_without_manifest(self, tmp_path):
        (tmp_path / "empty_dir").mkdir()
        manifests = scan_sources_dir(tmp_path)
        assert len(manifests) == 0

    def test_nonexistent_dir(self, tmp_path):
        manifests = scan_sources_dir(tmp_path / "nonexistent")
        assert len(manifests) == 0


class TestManifestCaptureSource:
    def test_name_and_table(self, zsh_manifest):
        source = ManifestCaptureSource(zsh_manifest)
        assert source.name == "zsh"
        assert source.db_table() == "zsh_data"

    def test_db_schema(self, zsh_manifest):
        source = ManifestCaptureSource(zsh_manifest)
        schema = source.db_schema()
        assert "CREATE TABLE IF NOT EXISTS zsh_data" in schema
        assert "timestamp text not null" in schema
        assert "command text not null" in schema
        assert "processed integer not null" in schema

    def test_db_columns(self, zsh_manifest):
        source = ManifestCaptureSource(zsh_manifest)
        cols = source.db_columns()
        assert "id" in cols
        assert "timestamp" in cols
        assert "command" in cols

    def test_validate_ingest(self, zsh_manifest):
        source = ManifestCaptureSource(zsh_manifest)
        data = source.validate_ingest({
            "timestamp": "2026-01-01", "command": "git status", "extra_field": "dropped"
        })
        assert data == {"timestamp": "2026-01-01", "command": "git status"}

    def test_validate_ingest_missing_timestamp(self, zsh_manifest):
        source = ManifestCaptureSource(zsh_manifest)
        with pytest.raises(ValueError, match="timestamp"):
            source.validate_ingest({"command": "test"})

    def test_to_frame(self, zsh_manifest):
        source = ManifestCaptureSource(zsh_manifest)
        frame = source.to_frame({
            "id": 1, "timestamp": "2026-01-01T00:00:00Z", "command": "git status"
        })
        assert frame.id == 1
        assert frame.source == "zsh"
        assert frame.text == "git status"
        assert frame.timestamp == "2026-01-01T00:00:00Z"

    def test_format_context(self, zsh_manifest):
        source = ManifestCaptureSource(zsh_manifest)
        frame = Frame(id=1, source="zsh", text="git status", app_name="zsh",
                      window_name="", timestamp="2026-01-01T00:00:00Z")
        ctx = source.format_context(frame)
        assert "[2026-01-01T00:00:00Z]" in ctx
        assert "git status" in ctx


class TestManifestRegistry:
    def test_register_and_query(self, zsh_manifest):
        registry = ManifestRegistry()
        registry.register(zsh_manifest)

        assert registry.has("zsh")
        assert not registry.has("bash")
        assert registry.names() == ["zsh"]
        assert registry.get_manifest("zsh").name == "zsh"
        assert registry.get_source("zsh").name == "zsh"

    def test_all_manifests(self, zsh_manifest):
        registry = ManifestRegistry()
        registry.register(zsh_manifest)
        assert len(registry.all_manifests()) == 1
        assert len(registry.all_sources()) == 1


class TestCreateTable:
    def test_creates_table_with_indexes(self, zsh_manifest, db_session):
        create_table_for_manifest(db_session, zsh_manifest)

        # Verify table exists
        result = db_session.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'zsh_data'"
        ))
        assert result.scalar() == "zsh_data"

        # Verify columns
        result = db_session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'zsh_data'"
        ))
        cols = {row[0] for row in result.fetchall()}
        assert "id" in cols
        assert "timestamp" in cols
        assert "command" in cols
        assert "processed" in cols
        assert "created_at" in cols

    def test_idempotent(self, zsh_manifest, db_session):
        create_table_for_manifest(db_session, zsh_manifest)
        create_table_for_manifest(db_session, zsh_manifest)  # Should not raise


class TestInsertAndQuery:
    def test_insert_and_query(self, zsh_manifest, db_session):
        create_table_for_manifest(db_session, zsh_manifest)

        row_id = insert_record(db_session, zsh_manifest, {
            "timestamp": "2026-01-01T00:00:00Z",
            "command": "git status",
        })
        assert row_id > 0

        records, total = query_records(db_session, zsh_manifest)
        assert total == 1
        assert records[0]["command"] == "git status"
        assert records[0]["timestamp"] == "2026-01-01T00:00:00Z"

    def test_query_with_search(self, zsh_manifest, db_session):
        create_table_for_manifest(db_session, zsh_manifest)

        insert_record(db_session, zsh_manifest, {"timestamp": "t1", "command": "git status"})
        insert_record(db_session, zsh_manifest, {"timestamp": "t2", "command": "npm install"})
        insert_record(db_session, zsh_manifest, {"timestamp": "t3", "command": "git log"})

        records, total = query_records(db_session, zsh_manifest, search="git")
        assert total == 2
        commands = {r["command"] for r in records}
        assert commands == {"git status", "git log"}

    def test_query_pagination(self, zsh_manifest, db_session):
        create_table_for_manifest(db_session, zsh_manifest)

        for i in range(10):
            insert_record(db_session, zsh_manifest, {"timestamp": f"t{i}", "command": f"cmd_{i}"})

        records, total = query_records(db_session, zsh_manifest, limit=3, offset=0)
        assert total == 10
        assert len(records) == 3

        records2, _ = query_records(db_session, zsh_manifest, limit=3, offset=3)
        assert len(records2) == 3
        # Different records due to offset
        assert records[0]["id"] != records2[0]["id"]

    def test_extra_fields_dropped(self, zsh_manifest, db_session):
        create_table_for_manifest(db_session, zsh_manifest)

        row_id = insert_record(db_session, zsh_manifest, {
            "timestamp": "t1",
            "command": "test",
            "unknown_field": "should be dropped",
        })
        assert row_id > 0

        records, _ = query_records(db_session, zsh_manifest)
        assert len(records) == 1
        assert records[0]["command"] == "test"
