"""Tools for agentic L2 distillation (non-MCP, ToolDef-based)."""

import sqlite3

from engine.llm.types import ToolDef
from engine.observability.logger import log_tool_call
from engine.agents import repository as repo

STAGE = "distill_agentic"


def _logged(conn, name, fn):
    def wrapper(**kwargs):
        result = fn(**kwargs)
        log_tool_call(conn, STAGE, name, kwargs, result)
        return result
    return wrapper


def make_distill_tools(conn: sqlite3.Connection) -> list[ToolDef]:
    """Create tools for the distill agent."""
    return [
        ToolDef(
            name="search_episodes",
            description="Search episodes by keyword in summary.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["query"],
            },
            handler=_logged(conn, "search_episodes",
                            lambda query, limit=10: repo.search_episodes(conn, query, limit)),
        ),
        ToolDef(
            name="get_episode_detail",
            description="Get full details of a specific episode by ID.",
            input_schema={
                "type": "object",
                "properties": {"episode_id": {"type": "integer"}},
                "required": ["episode_id"],
            },
            handler=_logged(conn, "get_episode_detail",
                            lambda episode_id: repo.get_episode_detail(conn, episode_id) or {"error": "not found"}),
        ),
        ToolDef(
            name="get_episode_frames",
            description="Get raw capture frames for an episode.",
            input_schema={
                "type": "object",
                "properties": {
                    "episode_id": {"type": "integer"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["episode_id"],
            },
            handler=_logged(conn, "get_episode_frames",
                            lambda episode_id, limit=10: repo.get_episode_frames(conn, episode_id, limit)),
        ),
        ToolDef(
            name="get_playbook_history",
            description="Get confidence/maturity history for a playbook entry.",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=_logged(conn, "get_playbook_history",
                            lambda name: repo.get_playbook_history(conn, name)),
        ),
        ToolDef(
            name="get_all_playbook_entries",
            description="List all current playbook entries.",
            input_schema={"type": "object", "properties": {}},
            handler=_logged(conn, "get_all_playbook_entries",
                            lambda: repo.get_all_playbook_entries(conn)),
        ),
        ToolDef(
            name="write_playbook_entry",
            description="Create or update a playbook entry.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "kebab-case name"},
                    "context": {"type": "string"},
                    "action": {"type": "string"},
                    "confidence": {"type": "number", "description": "0.0-1.0"},
                    "maturity": {"type": "string", "enum": ["nascent", "developing", "mature", "mastered"]},
                    "evidence": {"type": "string", "description": "JSON array of episode IDs"},
                },
                "required": ["name", "context", "action", "confidence", "maturity", "evidence"],
            },
            handler=_logged(conn, "write_playbook_entry",
                            lambda name, context, action, confidence, maturity, evidence:
                            (repo.write_playbook_entry(conn, name, context, action, confidence, maturity, evidence),
                             {"status": "ok", "name": name})[-1]),
        ),
    ]
