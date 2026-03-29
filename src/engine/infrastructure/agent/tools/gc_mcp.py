"""SDK MCP tools for agentic GC (garbage collection).

Combines dedup, audit, and purge tools. Uses Agent SDK's native
@tool + create_sdk_mcp_server.
"""

import json

from sqlalchemy.orm import sessionmaker

from claude_agent_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig
from engine.infrastructure.observability.logger import log_tool_call
from engine.infrastructure.agent import repository as repo

STAGE = "gc"


def create_gc_mcp_server(session_factory: sessionmaker) -> McpSdkServerConfig:
    """Create an SDK MCP server with all GC tools."""
    tools = (
        _dedup_tools(session_factory)
        + _audit_tools(session_factory)
        + _purge_tools(session_factory)
        + _security_tools(session_factory)
        + _manifest_purge_tools(session_factory)
    )
    return create_sdk_mcp_server(name="gc-tools", tools=tools)


def _dedup_tools(sf: sessionmaker) -> list:
    @tool("find_similar_pairs", "Find pairs of playbook entries with high name similarity.", {
        "threshold": float,
    })
    async def find_similar_pairs(args):
        session = sf()
        try:
            result = repo.find_similar_pairs(session, args.get("threshold", 0.8))
            log_tool_call(session, STAGE, "find_similar_pairs", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("merge_entries", "Merge two playbook entries. Keeps keep_id, deletes the other.", {
        "keep_id": int, "remove_id": int,
    })
    async def merge_entries(args):
        session = sf()
        try:
            result = repo.merge_entries(session, args["keep_id"], args["remove_id"])
            log_tool_call(session, STAGE, "merge_entries", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    return [find_similar_pairs, merge_entries]


def _audit_tools(sf: sessionmaker) -> list:
    @tool("check_evidence_exists", "Check if evidence episode IDs for a playbook entry still exist.", {
        "entry_name": str,
    })
    async def check_evidence_exists(args):
        session = sf()
        try:
            result = repo.check_evidence_exists(session, args["entry_name"])
            log_tool_call(session, STAGE, "check_evidence_exists", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("check_maturity_consistency", "Find entries where maturity doesn't match evidence count.", {})
    async def check_maturity_consistency(args):
        session = sf()
        try:
            result = repo.check_maturity_consistency(session)
            log_tool_call(session, STAGE, "check_maturity_consistency", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("record_snapshot", "Record current state of a playbook entry into history.", {
        "name": str, "reason": str,
    })
    async def record_snapshot(args):
        session = sf()
        try:
            result = repo.record_snapshot(session, args["name"], args.get("reason", ""))
            log_tool_call(session, STAGE, "record_snapshot", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("deprecate_entry", "Soft-deprecate a playbook entry (confidence=0).", {
        "entry_id": int, "reason": str,
    })
    async def deprecate_entry(args):
        session = sf()
        try:
            result = repo.deprecate_entry(session, args["entry_id"], args.get("reason", ""))
            log_tool_call(session, STAGE, "deprecate_entry", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    return [check_evidence_exists, check_maturity_consistency, record_snapshot, deprecate_entry]


def _purge_tools(sf: sessionmaker) -> list:
    @tool("get_data_stats", "Get row counts for all raw data tables.", {})
    async def get_data_stats(args):
        session = sf()
        try:
            result = repo.get_data_stats(session)
            log_tool_call(session, STAGE, "get_data_stats", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("get_oldest_processed", "Get oldest processed record timestamp in each table.", {})
    async def get_oldest_processed(args):
        session = sf()
        try:
            result = repo.get_oldest_processed(session)
            log_tool_call(session, STAGE, "get_oldest_processed", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("purge_processed_frames", "Delete processed screen frames older than N days.", {
        "older_than_days": int,
    })
    async def purge_processed_frames(args):
        session = sf()
        try:
            result = repo.purge_processed_frames(session, args["older_than_days"])
            log_tool_call(session, STAGE, "purge_processed_frames", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("purge_processed_audio", "Delete processed audio frames older than N days.", {
        "older_than_days": int,
    })
    async def purge_processed_audio(args):
        session = sf()
        try:
            result = repo.purge_processed_audio(session, args["older_than_days"])
            log_tool_call(session, STAGE, "purge_processed_audio", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("purge_processed_os_events", "Delete processed OS events older than N days.", {
        "older_than_days": int,
    })
    async def purge_processed_os_events(args):
        session = sf()
        try:
            result = repo.purge_processed_os_events(session, args["older_than_days"])
            log_tool_call(session, STAGE, "purge_processed_os_events", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("purge_pipeline_logs", "Delete pipeline logs older than N days.", {
        "older_than_days": int,
    })
    async def purge_pipeline_logs(args):
        session = sf()
        try:
            result = repo.purge_pipeline_logs(session, args["older_than_days"])
            log_tool_call(session, STAGE, "purge_pipeline_logs", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    return [get_data_stats, get_oldest_processed, purge_processed_frames,
            purge_processed_audio, purge_processed_os_events, purge_pipeline_logs]


def _security_tools(sf: sessionmaker) -> list:
    @tool("search_frames_for_sensitive", "SECURITY: Scan frame text for passwords, API keys, tokens.", {
        "limit": int,
    })
    async def search_frames_for_sensitive(args):
        session = sf()
        try:
            result = repo.search_frames_for_sensitive(session, args.get("limit", 100))
            log_tool_call(session, STAGE, "search_frames_for_sensitive", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("purge_sensitive_frames", "SECURITY: Delete frames containing sensitive data by ID.", {
        "frame_ids": str,
    })
    async def purge_sensitive_frames(args):
        session = sf()
        try:
            ids = json.loads(args["frame_ids"]) if isinstance(args["frame_ids"], str) else args["frame_ids"]
            result = repo.purge_sensitive_frames(session, ids)
            log_tool_call(session, STAGE, "purge_sensitive_frames", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    return [search_frames_for_sensitive, purge_sensitive_frames]


def _manifest_purge_tools(sf: sessionmaker) -> list:
    """Generate purge tools for manifest-based sources."""
    from engine.infrastructure.etl.sources.manifest_registry import get_global_registry

    registry = get_global_registry()
    if not registry:
        return []

    tools = []
    for manifest in registry.all_manifests():
        if not manifest.db_table:
            continue
        sn = manifest.name
        tbl = manifest.db_table
        display = manifest.display_name

        @tool(f"purge_{sn}", f"Delete processed {display} data older than N days.", {
            "older_than_days": int,
        })
        async def purge_source(args, _sn=sn, _tbl=tbl):
            from sqlalchemy import text
            from engine.infrastructure.persistence.session import ago
            session = sf()
            try:
                cutoff = ago(days=args["older_than_days"])
                result = session.execute(text(
                    f"DELETE FROM {_tbl} WHERE processed = 1 AND created_at < :cutoff"
                ), {"cutoff": cutoff})
                session.commit()
                out = {"source": _sn, "deleted": result.rowcount}
                log_tool_call(session, STAGE, f"purge_{_sn}", args, out)
                return {"content": [{"type": "text", "text": json.dumps(out, default=str)}]}
            finally:
                session.close()

        tools.append(purge_source)

    return tools
