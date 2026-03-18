"""Evidence audit tools + raw data GC for the GC agent."""

import sqlite3

from engine.llm.types import ToolDef
from engine.agents import repository as repo


def make_audit_tools(conn: sqlite3.Connection) -> list[ToolDef]:
    """Create audit tool definitions for the GC agent."""
    return [
        ToolDef(
            name="check_evidence_exists",
            description="Check if evidence episode IDs for a playbook entry still exist.",
            input_schema={
                "type": "object",
                "properties": {"entry_name": {"type": "string"}},
                "required": ["entry_name"],
            },
            handler=lambda entry_name: repo.check_evidence_exists(conn, entry_name),
        ),
        ToolDef(
            name="check_maturity_consistency",
            description="Find entries where maturity level doesn't match evidence count.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: repo.check_maturity_consistency(conn),
        ),
        ToolDef(
            name="record_snapshot",
            description="Record current state of a playbook entry into history before changes.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["name"],
            },
            handler=lambda name, reason="": _record_snapshot(conn, name, reason),
        ),
        ToolDef(
            name="deprecate_entry",
            description="Soft-deprecate a playbook entry (confidence=0, maturity=nascent).",
            input_schema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["entry_id"],
            },
            handler=lambda entry_id, reason="": repo.deprecate_entry(conn, entry_id, reason),
        ),
        ToolDef(
            name="get_data_stats",
            description="Get row counts for all raw data tables.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: repo.get_data_stats(conn),
        ),
        ToolDef(
            name="get_oldest_processed",
            description="Get oldest processed record timestamp in each table.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: repo.get_oldest_processed(conn),
        ),
        ToolDef(
            name="purge_processed_frames",
            description="Delete processed screen frames older than N days + image files.",
            input_schema={
                "type": "object",
                "properties": {"older_than_days": {"type": "integer"}},
                "required": ["older_than_days"],
            },
            handler=lambda older_than_days: repo.purge_processed_frames(conn, older_than_days),
        ),
        ToolDef(
            name="purge_processed_audio",
            description="Delete processed audio frames older than N days + chunk files.",
            input_schema={
                "type": "object",
                "properties": {"older_than_days": {"type": "integer"}},
                "required": ["older_than_days"],
            },
            handler=lambda older_than_days: repo.purge_processed_audio(conn, older_than_days),
        ),
        ToolDef(
            name="purge_processed_os_events",
            description="Delete processed OS events older than N days.",
            input_schema={
                "type": "object",
                "properties": {"older_than_days": {"type": "integer"}},
                "required": ["older_than_days"],
            },
            handler=lambda older_than_days: repo.purge_processed_os_events(conn, older_than_days),
        ),
        ToolDef(
            name="purge_pipeline_logs",
            description="Delete pipeline logs older than N days.",
            input_schema={
                "type": "object",
                "properties": {"older_than_days": {"type": "integer"}},
                "required": ["older_than_days"],
            },
            handler=lambda older_than_days: repo.purge_pipeline_logs(conn, older_than_days),
        ),
    ]


def _record_snapshot(conn: sqlite3.Connection, name: str, reason: str) -> dict:
    """Wrapper that fetches entry then calls repo."""
    entry = repo.get_playbook_by_name(conn, name)
    if not entry:
        return {"error": f"Entry '{name}' not found"}
    repo.record_playbook_snapshot(
        conn, name, entry["confidence"], entry["maturity"] or "nascent",
        entry["evidence"] or "[]", reason,
    )
    return {"name": name, "snapshot_confidence": entry["confidence"],
            "snapshot_maturity": entry["maturity"], "reason": reason}
