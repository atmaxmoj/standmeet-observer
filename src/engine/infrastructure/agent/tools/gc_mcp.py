"""In-process MCP server for agentic GC (garbage collection).

Combines dedup, audit, and purge tools. Each tool call creates its own
DB session to avoid concurrency issues.
"""

import json

from sqlalchemy.orm import sessionmaker
from mcp.server.fastmcp import FastMCP

from engine.infrastructure.observability.logger import log_tool_call
from engine.infrastructure.agent import repository as repo

STAGE = "gc"


def create_gc_mcp_server(session_factory: sessionmaker) -> FastMCP:
    """Create an in-process MCP server with all GC tools."""
    mcp = FastMCP("gc-tools")
    _register_dedup_tools(mcp, session_factory)
    _register_audit_tools(mcp, session_factory)
    _register_purge_tools(mcp, session_factory)
    _register_security_tools(mcp, session_factory)
    _register_manifest_purge_tools(mcp, session_factory)
    return mcp


def _register_dedup_tools(mcp: FastMCP, session_factory: sessionmaker):
    @mcp.tool()
    def find_similar_pairs(threshold: float = 0.8) -> str:
        """Find pairs of playbook entries with high name similarity (Jaccard)."""
        session = session_factory()
        try:
            result = repo.find_similar_pairs(session, threshold)
            log_tool_call(session, STAGE, "find_similar_pairs", {"threshold": threshold}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def merge_entries(keep_id: int, remove_id: int) -> str:
        """Merge two playbook entries. Keeps keep_id, combines evidence, deletes the other."""
        session = session_factory()
        try:
            result = repo.merge_entries(session, keep_id, remove_id)
            log_tool_call(session, STAGE, "merge_entries", {"keep_id": keep_id, "remove_id": remove_id}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()



def _register_audit_tools(mcp: FastMCP, session_factory: sessionmaker):
    @mcp.tool()
    def check_evidence_exists(entry_name: str) -> str:
        """Check if evidence episode IDs for a playbook entry still exist."""
        session = session_factory()
        try:
            result = repo.check_evidence_exists(session, entry_name)
            log_tool_call(session, STAGE, "check_evidence_exists", {"entry_name": entry_name}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def check_maturity_consistency() -> str:
        """Find entries where maturity level doesn't match evidence count."""
        session = session_factory()
        try:
            result = repo.check_maturity_consistency(session)
            log_tool_call(session, STAGE, "check_maturity_consistency", {}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def record_snapshot(name: str, reason: str = "") -> str:
        """Record current state of a playbook entry into history before changes."""
        session = session_factory()
        try:
            result = repo.record_snapshot(session, name, reason)
            log_tool_call(session, STAGE, "record_snapshot", {"name": name}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def deprecate_entry(entry_id: int, reason: str = "") -> str:
        """Soft-deprecate a playbook entry (confidence=0, maturity=nascent)."""
        session = session_factory()
        try:
            result = repo.deprecate_entry(session, entry_id, reason)
            log_tool_call(session, STAGE, "deprecate_entry", {"entry_id": entry_id}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()



def _register_purge_tools(mcp: FastMCP, session_factory: sessionmaker):
    _register_stats_tools(mcp, session_factory)
    _register_delete_tools(mcp, session_factory)


def _register_stats_tools(mcp: FastMCP, session_factory: sessionmaker):
    @mcp.tool()
    def get_data_stats() -> str:
        """Get row counts for all raw data tables."""
        session = session_factory()
        try:
            result = repo.get_data_stats(session)
            log_tool_call(session, STAGE, "get_data_stats", {}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def get_oldest_processed() -> str:
        """Get oldest processed record timestamp in each table."""
        session = session_factory()
        try:
            result = repo.get_oldest_processed(session)
            log_tool_call(session, STAGE, "get_oldest_processed", {}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()


def _register_delete_tools(mcp: FastMCP, session_factory: sessionmaker):
    @mcp.tool()
    def purge_processed_frames(older_than_days: int) -> str:
        """Delete processed screen frames older than N days + image files."""
        session = session_factory()
        try:
            result = repo.purge_processed_frames(session, older_than_days)
            log_tool_call(session, STAGE, "purge_processed_frames", {"older_than_days": older_than_days}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def purge_processed_audio(older_than_days: int) -> str:
        """Delete processed audio frames older than N days + chunk files."""
        session = session_factory()
        try:
            result = repo.purge_processed_audio(session, older_than_days)
            log_tool_call(session, STAGE, "purge_processed_audio", {"older_than_days": older_than_days}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def purge_processed_os_events(older_than_days: int) -> str:
        """Delete processed OS events older than N days."""
        session = session_factory()
        try:
            result = repo.purge_processed_os_events(session, older_than_days)
            log_tool_call(session, STAGE, "purge_processed_os_events", {"older_than_days": older_than_days}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def purge_pipeline_logs(older_than_days: int) -> str:
        """Delete pipeline logs older than N days."""
        session = session_factory()
        try:
            result = repo.purge_pipeline_logs(session, older_than_days)
            log_tool_call(session, STAGE, "purge_pipeline_logs", {"older_than_days": older_than_days}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()



def _register_security_tools(mcp: FastMCP, session_factory: sessionmaker):
    @mcp.tool()
    def search_frames_for_sensitive(limit: int = 100) -> str:
        """SECURITY: Scan frame text for passwords, API keys, tokens, secrets."""
        session = session_factory()
        try:
            result = repo.search_frames_for_sensitive(session, limit)
            log_tool_call(session, STAGE, "search_frames_for_sensitive", {"limit": limit}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def purge_sensitive_frames(frame_ids: list[int]) -> str:
        """SECURITY: Delete frames containing sensitive data by ID."""
        session = session_factory()
        try:
            result = repo.purge_sensitive_frames(session, frame_ids)
            log_tool_call(session, STAGE, "purge_sensitive_frames", {"frame_ids": frame_ids}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()



def _register_manifest_purge_tools(mcp: FastMCP, session_factory: sessionmaker):
    """Register purge tools for manifest-based sources."""
    from engine.infrastructure.etl.sources.manifest_registry import get_global_registry

    registry = get_global_registry()
    if not registry:
        return

    for manifest in registry.all_manifests():
        if not manifest.db_table:
            continue
        source_name = manifest.name
        table = manifest.db_table
        display = manifest.display_name

        def make_purge_fn(sn, tbl):
            def purge(older_than_days: int) -> str:
                from sqlalchemy import text
                from engine.infrastructure.persistence.session import ago
                session = session_factory()
                try:
                    cutoff = ago(days=older_than_days)
                    result = session.execute(text(
                        f"DELETE FROM {tbl} WHERE processed = 1 AND created_at < :cutoff"
                    ), {"cutoff": cutoff})
                    session.commit()
                    out = {"source": sn, "deleted": result.rowcount}
                    log_tool_call(session, STAGE, f"purge_{sn}", {"older_than_days": older_than_days}, out)
                    return json.dumps(out, default=str)
                finally:
                    session.close()
            return purge

        mcp.tool(name=f"purge_{source_name}", description=f"Delete processed {display} data older than N days.")(
            make_purge_fn(source_name, table)
        )
