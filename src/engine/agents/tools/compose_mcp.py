"""In-process MCP server for agentic L3 routine composition.

Exposes episode/playbook read tools + routine write tools.
"""

import json
import logging
import sqlite3

from mcp.server.fastmcp import FastMCP

from engine.observability.logger import log_tool_call

logger = logging.getLogger(__name__)

STAGE = "compose_agentic"


def create_compose_mcp_server(conn: sqlite3.Connection) -> FastMCP:
    """Create an in-process MCP server with routine composition tools."""
    mcp = FastMCP("compose-tools")

    @mcp.tool()
    def search_episodes(query: str, limit: int = 10) -> str:
        """Search episodes by keyword in summary. Returns matching episodes."""
        words = query.strip().split()
        if len(words) > 1:
            where = " AND ".join("summary LIKE ?" for _ in words)
            params = [f"%{w}%" for w in words]
        else:
            where = "summary LIKE ?"
            params = [f"%{query}%"]
        rows = conn.execute(
            f"SELECT id, summary, app_names, started_at, ended_at "
            f"FROM episodes WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
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
    def get_all_playbook_entries() -> str:
        """List all current playbook entries (atomic behaviors)."""
        rows = conn.execute(
            "SELECT name, context, action, confidence, maturity, evidence "
            "FROM playbook_entries ORDER BY confidence DESC",
        ).fetchall()
        result = [dict(r) for r in rows]
        log_tool_call(conn, STAGE, "get_all_playbook_entries", {}, result)
        return json.dumps(result, default=str)

    @mcp.tool()
    def get_all_routines() -> str:
        """List all current routines."""
        rows = conn.execute(
            "SELECT name, trigger, goal, steps, uses, confidence, maturity "
            "FROM routines ORDER BY confidence DESC",
        ).fetchall()
        result = [dict(r) for r in rows]
        log_tool_call(conn, STAGE, "get_all_routines", {}, result)
        return json.dumps(result, default=str)

    @mcp.tool()
    def write_routine(
        name: str, trigger: str, goal: str,
        steps: str, uses: str,
        confidence: float, maturity: str,
    ) -> str:
        """Create or update a routine.

        steps: JSON array of step descriptions (strings)
        uses: JSON array of playbook entry names referenced by this routine
        """
        conn.execute(
            "INSERT INTO routines (name, trigger, goal, steps, uses, confidence, maturity, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET "
            "trigger=excluded.trigger, goal=excluded.goal, steps=excluded.steps, "
            "uses=excluded.uses, confidence=excluded.confidence, maturity=excluded.maturity, "
            "updated_at=datetime('now')",
            (name, trigger, goal, steps, uses, confidence, maturity),
        )
        result = {"status": "ok", "name": name}
        log_tool_call(conn, STAGE, "write_routine",
                      {"name": name, "confidence": confidence}, result)
        return json.dumps(result)

    return mcp
