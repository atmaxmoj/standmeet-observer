"""Evidence audit tools + raw data GC for the GC agent."""

from sqlalchemy.orm import Session

from engine.infrastructure.llm.types import ToolDef
from engine.infrastructure.agent import repository as repo


def make_audit_tools(session: Session) -> list[ToolDef]:
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
            handler=lambda entry_name: repo.check_evidence_exists(session, entry_name),
        ),
        ToolDef(
            name="check_maturity_consistency",
            description="Find entries where maturity level doesn't match evidence count.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: repo.check_maturity_consistency(session),
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
            handler=lambda name, reason="": _record_snapshot(session, name, reason),
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
            handler=lambda entry_id, reason="": repo.deprecate_entry(session, entry_id, reason),
        ),
        ToolDef(
            name="get_data_stats",
            description="Get row counts for all raw data tables.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: repo.get_data_stats(session),
        ),
        ToolDef(
            name="get_oldest_processed",
            description="Get oldest processed record timestamp in each table.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: repo.get_oldest_processed(session),
        ),
        ToolDef(
            name="purge_processed_frames",
            description="Delete processed screen frames older than N days + image files.",
            input_schema={
                "type": "object",
                "properties": {"older_than_days": {"type": "integer"}},
                "required": ["older_than_days"],
            },
            handler=lambda older_than_days: repo.purge_processed_frames(session, older_than_days),
        ),
        ToolDef(
            name="purge_processed_audio",
            description="Delete processed audio frames older than N days + chunk files.",
            input_schema={
                "type": "object",
                "properties": {"older_than_days": {"type": "integer"}},
                "required": ["older_than_days"],
            },
            handler=lambda older_than_days: repo.purge_processed_audio(session, older_than_days),
        ),
        ToolDef(
            name="purge_processed_os_events",
            description="Delete processed OS events older than N days.",
            input_schema={
                "type": "object",
                "properties": {"older_than_days": {"type": "integer"}},
                "required": ["older_than_days"],
            },
            handler=lambda older_than_days: repo.purge_processed_os_events(session, older_than_days),
        ),
        ToolDef(
            name="purge_pipeline_logs",
            description="Delete pipeline logs older than N days.",
            input_schema={
                "type": "object",
                "properties": {"older_than_days": {"type": "integer"}},
                "required": ["older_than_days"],
            },
            handler=lambda older_than_days: repo.purge_pipeline_logs(session, older_than_days),
        ),
        # -- Sensitive data tools --
        ToolDef(
            name="search_frames_for_sensitive",
            description="SECURITY: Scan frame text for passwords, API keys, tokens, secrets. "
                       "Returns frames containing sensitive patterns. Run this FIRST in every GC cycle.",
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 100}},
                "required": [],
            },
            handler=lambda limit=100: repo.search_frames_for_sensitive(session, limit),
        ),
        ToolDef(
            name="purge_sensitive_frames",
            description="SECURITY: Delete frames containing sensitive data by ID. "
                       "Use after search_frames_for_sensitive identifies frames to purge.",
            input_schema={
                "type": "object",
                "properties": {
                    "frame_ids": {"type": "array", "items": {"type": "integer"},
                                  "description": "IDs of frames to delete"},
                },
                "required": ["frame_ids"],
            },
            handler=lambda frame_ids: repo.purge_sensitive_frames(session, frame_ids),
        ),
    ]


def make_manifest_purge_tools(session: Session) -> list[ToolDef]:
    """Generate purge tools for manifest-based sources."""
    from engine.infrastructure.etl.sources.manifest_registry import get_global_registry
    from sqlalchemy import text

    registry = get_global_registry()
    if not registry:
        return []

    tools = []
    for manifest in registry.all_manifests():
        if not manifest.db_table:
            continue
        source_name = manifest.name
        table = manifest.db_table

        def make_purge(sn, tbl):
            def purge(older_than_days):
                from engine.infrastructure.persistence.session import ago
                cutoff = ago(days=older_than_days)
                result = session.execute(text(
                    f"DELETE FROM {tbl} WHERE processed = 1 AND created_at < :cutoff"
                ), {"cutoff": cutoff})
                session.commit()
                return {"source": sn, "deleted": result.rowcount}
            return purge

        gc_desc = manifest.gc.get("prompt", f"Purge old {source_name} data") if manifest.gc else f"Purge old {source_name} data"
        tools.append(ToolDef(
            name=f"purge_{source_name}",
            description=f"Delete processed {manifest.display_name} data older than N days. {gc_desc}",
            input_schema={
                "type": "object",
                "properties": {"older_than_days": {"type": "integer"}},
                "required": ["older_than_days"],
            },
            handler=make_purge(source_name, table),
        ))

    return tools


def _record_snapshot(session: Session, name: str, reason: str) -> dict:
    """Wrapper that fetches entry then calls repo."""
    entry = repo.get_playbook_by_name(session, name)
    if not entry:
        return {"error": f"Entry '{name}' not found"}
    repo.record_playbook_snapshot(
        session, name, entry["confidence"], entry["maturity"] or "nascent",
        entry["evidence"] or "[]", reason,
    )
    return {"name": name, "snapshot_confidence": entry["confidence"],
            "snapshot_maturity": entry["maturity"], "reason": reason}
