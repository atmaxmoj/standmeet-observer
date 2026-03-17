"""Tools for agentic L2 distillation.

These tools let the distill agent investigate episodes and manage playbook entries.
Used with LLMClient.complete_with_tools() for multi-turn distillation.
"""

import logging
import sqlite3

from engine.infra.llm import ToolDef
from engine.infra.log_mutation import log_tool_call

logger = logging.getLogger(__name__)

STAGE = "distill_agentic"


def _logged(conn, name, fn):
    """Wrap a tool handler to auto-log every call."""
    def wrapper(**kwargs):
        result = fn(**kwargs)
        log_tool_call(conn, STAGE, name, kwargs, result)
        return result
    return wrapper


def make_distill_tools(conn: sqlite3.Connection) -> list[ToolDef]:
    """Create tools for the distill agent."""

    def search_episodes(query: str, limit: int = 10) -> list[dict]:
        """Search episodes by keyword in summary."""
        rows = conn.execute(
            "SELECT id, summary, app_names, started_at, ended_at "
            "FROM episodes WHERE summary LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_episode_detail(episode_id: int) -> dict:
        """Get full episode with frame range for deeper inspection."""
        row = conn.execute(
            "SELECT * FROM episodes WHERE id = ?", (episode_id,),
        ).fetchone()
        if not row:
            return {"error": f"Episode {episode_id} not found"}
        return dict(row)

    def get_episode_frames(episode_id: int, limit: int = 10) -> list[dict]:
        """Get raw capture frames for an episode (for verification)."""
        ep = conn.execute(
            "SELECT frame_id_min, frame_id_max FROM episodes WHERE id = ?",
            (episode_id,),
        ).fetchone()
        if not ep:
            return [{"error": f"Episode {episode_id} not found"}]
        rows = conn.execute(
            "SELECT id, timestamp, app_name, window_name, substr(text, 1, 200) as text "
            "FROM frames WHERE id BETWEEN ? AND ? ORDER BY id LIMIT ?",
            (ep["frame_id_min"], ep["frame_id_max"], limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_playbook_history(name: str) -> list[dict]:
        """Get confidence/maturity history for a playbook entry."""
        rows = conn.execute(
            "SELECT confidence, maturity, change_reason, created_at "
            "FROM playbook_history WHERE playbook_name = ? ORDER BY created_at",
            (name,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_playbook_entries() -> list[dict]:
        """List all current playbook entries."""
        rows = conn.execute(
            "SELECT name, context, action, confidence, maturity, evidence "
            "FROM playbook_entries ORDER BY confidence DESC",
        ).fetchall()
        return [dict(r) for r in rows]

    def write_playbook_entry(
        name: str, context: str, action: str,
        confidence: float, maturity: str, evidence: str,
    ) -> dict:
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
        return {"status": "ok", "name": name}

    return [
        ToolDef(
            name="search_episodes",
            description="Search episodes by keyword in summary. Returns matching episodes.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["query"],
            },
            handler=_logged(conn, "search_episodes", lambda **kw: search_episodes(**kw)),
        ),
        ToolDef(
            name="get_episode_detail",
            description="Get full details of a specific episode by ID.",
            input_schema={
                "type": "object",
                "properties": {"episode_id": {"type": "integer"}},
                "required": ["episode_id"],
            },
            handler=_logged(conn, "get_episode_detail", lambda **kw: get_episode_detail(**kw)),
        ),
        ToolDef(
            name="get_episode_frames",
            description="Get raw capture frames for an episode. Use this to verify patterns by checking the actual screen data.",
            input_schema={
                "type": "object",
                "properties": {
                    "episode_id": {"type": "integer"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["episode_id"],
            },
            handler=_logged(conn, "get_episode_frames", lambda **kw: get_episode_frames(**kw)),
        ),
        ToolDef(
            name="get_playbook_history",
            description="Get the confidence/maturity history for a playbook entry over time.",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=_logged(conn, "get_playbook_history", lambda **kw: get_playbook_history(**kw)),
        ),
        ToolDef(
            name="get_all_playbook_entries",
            description="List all current playbook entries with their confidence and maturity.",
            input_schema={"type": "object", "properties": {}},
            handler=_logged(conn, "get_all_playbook_entries", lambda **kw: get_all_playbook_entries()),
        ),
        ToolDef(
            name="write_playbook_entry",
            description="Create or update a playbook entry. Call this when you've identified a behavioral pattern.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "kebab-case name"},
                    "context": {"type": "string", "description": "When does this rule apply?"},
                    "action": {"type": "string", "description": "What they do (JSON with intuition, action, why, counterexample)"},
                    "confidence": {"type": "number", "description": "0.0-1.0"},
                    "maturity": {"type": "string", "enum": ["nascent", "developing", "mature", "mastered"]},
                    "evidence": {"type": "string", "description": "JSON array of episode IDs"},
                },
                "required": ["name", "context", "action", "confidence", "maturity", "evidence"],
            },
            handler=_logged(conn, "write_playbook_entry", lambda **kw: write_playbook_entry(**kw)),
        ),
    ]
