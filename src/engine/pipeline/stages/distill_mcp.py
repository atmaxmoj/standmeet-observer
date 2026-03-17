"""In-process MCP server for agentic L2 distillation.

Exposes distill tools as MCP tools so Agent SDK query() can use them
with OAuth tokens (no direct API call needed).
"""

import json
import logging
import sqlite3

from mcp.server.fastmcp import FastMCP

from engine.infra.log_mutation import log_tool_call

logger = logging.getLogger(__name__)

STAGE = "distill_agentic"


def create_distill_mcp_server(conn: sqlite3.Connection) -> FastMCP:
    """Create an in-process MCP server with distill tools."""
    mcp = FastMCP("distill-tools")

    @mcp.tool()
    def search_episodes(query: str, limit: int = 10) -> str:
        """Search episodes by keyword in summary. Returns matching episodes."""
        rows = conn.execute(
            "SELECT id, summary, app_names, started_at, ended_at "
            "FROM episodes WHERE summary LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        result = [dict(r) for r in rows]
        log_tool_call(conn, STAGE, "search_episodes", {"query": query, "limit": limit}, result)
        return json.dumps(result, default=str)

    @mcp.tool()
    def get_episode_detail(episode_id: int) -> str:
        """Get full details of a specific episode by ID."""
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        result = dict(row) if row else {"error": f"Episode {episode_id} not found"}
        log_tool_call(conn, STAGE, "get_episode_detail", {"episode_id": episode_id}, result)
        return json.dumps(result, default=str)

    @mcp.tool()
    def get_episode_frames(episode_id: int, limit: int = 10) -> str:
        """Get raw capture frames for an episode to verify patterns."""
        ep = conn.execute(
            "SELECT frame_id_min, frame_id_max FROM episodes WHERE id = ?", (episode_id,),
        ).fetchone()
        if not ep:
            return json.dumps({"error": f"Episode {episode_id} not found"})
        rows = conn.execute(
            "SELECT id, timestamp, app_name, window_name, substr(text, 1, 200) as text "
            "FROM frames WHERE id BETWEEN ? AND ? ORDER BY id LIMIT ?",
            (ep["frame_id_min"], ep["frame_id_max"], limit),
        ).fetchall()
        result = [dict(r) for r in rows]
        log_tool_call(conn, STAGE, "get_episode_frames", {"episode_id": episode_id}, result)
        return json.dumps(result, default=str)

    @mcp.tool()
    def get_playbook_history(name: str) -> str:
        """Get confidence/maturity history for a playbook entry."""
        rows = conn.execute(
            "SELECT confidence, maturity, change_reason, created_at "
            "FROM playbook_history WHERE playbook_name = ? ORDER BY created_at",
            (name,),
        ).fetchall()
        result = [dict(r) for r in rows]
        log_tool_call(conn, STAGE, "get_playbook_history", {"name": name}, result)
        return json.dumps(result, default=str)

    @mcp.tool()
    def get_all_playbook_entries() -> str:
        """List all current playbook entries."""
        rows = conn.execute(
            "SELECT name, context, action, confidence, maturity, evidence "
            "FROM playbook_entries ORDER BY confidence DESC",
        ).fetchall()
        result = [dict(r) for r in rows]
        log_tool_call(conn, STAGE, "get_all_playbook_entries", {}, result)
        return json.dumps(result, default=str)

    @mcp.tool()
    def write_playbook_entry(
        name: str, context: str, action: str,
        confidence: float, maturity: str, evidence: str,
    ) -> str:
        """Create or update a playbook entry."""
        conn.execute(
            "INSERT INTO playbook_entries (name, context, action, confidence, "
            "maturity, evidence, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET "
            "context=excluded.context, action=excluded.action, "
            "confidence=excluded.confidence, maturity=excluded.maturity, "
            "evidence=excluded.evidence, updated_at=datetime('now')",
            (name, context, action, confidence, maturity, evidence),
        )
        result = {"status": "ok", "name": name}
        log_tool_call(conn, STAGE, "write_playbook_entry",
                      {"name": name, "confidence": confidence}, result)
        return json.dumps(result)

    return mcp
