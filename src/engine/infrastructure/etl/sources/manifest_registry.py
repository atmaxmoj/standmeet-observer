"""ManifestRegistry — scans source directories, loads manifests, creates tables.

This extends the existing SourceRegistry with manifest-driven source management.
It handles:
1. Scanning directories for manifest.json files
2. Creating DB tables from manifest db definitions
3. Providing unified ingest/query for manifest-based sources
4. Generating CaptureSource adapters for ETL compatibility
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from engine.domain.observation.entity import Frame
from engine.infrastructure.etl.sources.base import CaptureSource

logger = logging.getLogger(__name__)


@dataclass
class ManifestData:
    """Parsed manifest.json — lightweight, no dependency on source_framework package."""

    name: str
    version: str = "0.1.0"
    display_name: str = ""
    description: str = ""
    author: str = "builtin"
    platform: list[str] = field(default_factory=list)
    entrypoint: str = ""
    events: dict = field(default_factory=dict)
    db_table: str = ""
    db_columns: dict[str, str] = field(default_factory=dict)
    db_indexes: list[str] = field(default_factory=list)
    ui: dict = field(default_factory=dict)
    context_description: str = ""
    context_format: str = ""
    gc: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    # Raw JSON for the /engine/sources endpoint
    raw: dict = field(default_factory=dict)


def load_manifest_data(path: Path) -> ManifestData:
    """Load a manifest.json into ManifestData (no source_framework dependency)."""
    if path.is_dir():
        path = path / "manifest.json"

    with open(path) as f:
        raw = json.load(f)

    db = raw.get("db", {})
    ctx = raw.get("context", {})

    return ManifestData(
        name=raw["name"],
        version=raw.get("version", "0.1.0"),
        display_name=raw.get("display_name", raw["name"]),
        description=raw.get("description", ""),
        author=raw.get("author", "builtin"),
        platform=raw.get("platform", []),
        entrypoint=raw.get("entrypoint", ""),
        events=raw.get("events", {}),
        db_table=db.get("table", ""),
        db_columns=db.get("columns", {}),
        db_indexes=db.get("indexes", []),
        ui=raw.get("ui", {}),
        context_description=ctx.get("description", ""),
        context_format=ctx.get("format", ""),
        gc=raw.get("gc", {}),
        config=raw.get("config", {}),
        raw=raw,
    )


class ManifestCaptureSource(CaptureSource):
    """CaptureSource adapter generated from a manifest.

    Bridges manifest-based sources into the existing ETL pipeline.
    """

    def __init__(self, manifest: ManifestData):
        self._manifest = manifest

    @property
    def name(self) -> str:
        return self._manifest.name

    def db_table(self) -> str:
        return self._manifest.db_table

    def db_schema(self) -> str:
        cols = ["id SERIAL PRIMARY KEY"]
        for col_name, col_type in self._manifest.db_columns.items():
            cols.append(f"{col_name} {col_type}")
        cols.append("created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        return f"CREATE TABLE IF NOT EXISTS {self._manifest.db_table} ({', '.join(cols)})"

    def db_columns(self) -> list[str]:
        return ["id"] + list(self._manifest.db_columns.keys())

    def validate_ingest(self, data: dict) -> dict:
        if "timestamp" not in data:
            raise ValueError("Missing required field: timestamp")
        # Filter to only known columns
        known = set(self._manifest.db_columns.keys())
        return {k: v for k, v in data.items() if k in known}

    def to_frame(self, row: dict) -> Frame:
        """Convert a DB row to a Frame using manifest context.format as hints."""
        # Try to map common fields
        return Frame(
            id=row.get("id", 0),
            source=self._manifest.name,
            text=row.get("text", row.get("command", row.get("data", ""))),
            app_name=row.get("app_name", row.get("event_type", self._manifest.name)),
            window_name=row.get("window_name", row.get("source", "")),
            timestamp=row.get("timestamp", ""),
            image_path=row.get("image_path", ""),
        )

    def format_context(self, frame: Frame) -> str:
        fmt = self._manifest.context_format
        if fmt:
            try:
                return fmt.format(
                    timestamp=frame.timestamp,
                    app_name=frame.app_name,
                    window_name=frame.window_name,
                    text=frame.text[:300],
                    source=frame.source,
                )
            except (KeyError, IndexError):
                pass
        return f"[{frame.timestamp}] [{self._manifest.name}]: {frame.text[:300]}"


class ManifestRegistry:
    """Registry for manifest-based sources. Complements the existing SourceRegistry."""

    def __init__(self):
        self._manifests: dict[str, ManifestData] = {}
        self._sources: dict[str, ManifestCaptureSource] = {}

    def register(self, manifest: ManifestData):
        """Register a manifest-based source."""
        self._manifests[manifest.name] = manifest
        self._sources[manifest.name] = ManifestCaptureSource(manifest)
        logger.info("Registered manifest source: %s (table=%s)", manifest.name, manifest.db_table)

    def get_manifest(self, name: str) -> ManifestData:
        return self._manifests[name]

    def get_source(self, name: str) -> ManifestCaptureSource:
        return self._sources[name]

    def all_manifests(self) -> list[ManifestData]:
        return list(self._manifests.values())

    def all_sources(self) -> list[ManifestCaptureSource]:
        return list(self._sources.values())

    def names(self) -> list[str]:
        return list(self._manifests.keys())

    def has(self, name: str) -> bool:
        return name in self._manifests


def scan_sources_dir(sources_dir: Path) -> list[ManifestData]:
    """Scan a directory for subdirectories containing manifest.json."""
    manifests = []
    if not sources_dir.is_dir():
        logger.warning("Sources directory not found: %s", sources_dir)
        return manifests

    for child in sorted(sources_dir.iterdir()):
        manifest_path = child / "manifest.json"
        if manifest_path.is_file():
            try:
                m = load_manifest_data(manifest_path)
                manifests.append(m)
                logger.debug("Found source manifest: %s in %s", m.name, child)
            except Exception:
                logger.exception("Failed to load manifest from %s", manifest_path)
    return manifests


def create_table_for_manifest(session: Session, manifest: ManifestData):
    """Create the DB table for a manifest-based source (idempotent)."""
    source = ManifestCaptureSource(manifest)
    schema = source.db_schema()
    session.execute(text(schema))

    for col in manifest.db_indexes:
        idx_name = f"idx_{manifest.db_table}_{col}"
        session.execute(text(
            f"CREATE INDEX IF NOT EXISTS {idx_name} ON {manifest.db_table} ({col})"
        ))

    session.commit()
    logger.info("Ensured table '%s' with indexes %s", manifest.db_table, manifest.db_indexes)


def insert_record(session: Session, manifest: ManifestData, data: dict) -> int:
    """Insert a record into a manifest-based source's table."""
    source = ManifestCaptureSource(manifest)
    validated = source.validate_ingest(data)

    cols = list(validated.keys())
    placeholders = [f":{k}" for k in cols]
    sql = f"INSERT INTO {manifest.db_table} ({', '.join(cols)}) VALUES ({', '.join(placeholders)}) RETURNING id"

    result = session.execute(text(sql), validated)
    row_id = result.scalar() or 0
    session.commit()
    return row_id


def query_records(
    session: Session,
    manifest: ManifestData,
    limit: int = 50,
    offset: int = 0,
    search: str = "",
) -> tuple[list[dict], int]:
    """Query records from a manifest-based source's table."""
    table = manifest.db_table
    searchable = manifest.ui.get("searchable_columns", [])

    # Count
    count_sql = f"SELECT COUNT(*) FROM {table}"
    where_clauses = []
    params: dict = {}

    if search and searchable:
        conditions = [f"{col} LIKE :search" for col in searchable]
        where_clauses.append(f"({' OR '.join(conditions)})")
        params["search"] = f"%{search}%"

    if where_clauses:
        count_sql += " WHERE " + " AND ".join(where_clauses)

    total = session.execute(text(count_sql), params).scalar() or 0

    # Query
    all_cols = ["id"] + list(manifest.db_columns.keys()) + ["created_at"]
    select_sql = f"SELECT {', '.join(all_cols)} FROM {table}"
    if where_clauses:
        select_sql += " WHERE " + " AND ".join(where_clauses)
    select_sql += " ORDER BY id DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    rows = session.execute(text(select_sql), params).mappings().all()
    return [dict(r) for r in rows], total


# Module-level singleton for use by Huey tasks (which can't access app.state)
_global_registry: ManifestRegistry | None = None


def get_global_registry() -> ManifestRegistry | None:
    """Get the global ManifestRegistry singleton. Returns None if not initialized."""
    return _global_registry


def set_global_registry(registry: ManifestRegistry):
    """Set the global ManifestRegistry singleton."""
    global _global_registry
    _global_registry = registry
