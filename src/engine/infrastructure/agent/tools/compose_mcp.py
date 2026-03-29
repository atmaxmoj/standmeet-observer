"""In-process MCP server for agentic L3 routine composition.

Each tool call creates its own DB session to avoid concurrency issues
when the Agent SDK dispatches parallel tool calls.
"""

import json

from sqlalchemy.orm import sessionmaker
from mcp.server.fastmcp import FastMCP

from engine.infrastructure.observability.logger import log_tool_call
from engine.infrastructure.agent import repository as repo

STAGE = "compose_agentic"


def create_compose_mcp_server(session_factory: sessionmaker) -> FastMCP:
    """Create an in-process MCP server with routine composition tools.

    Args:
        session_factory: SQLAlchemy session factory — each tool call gets its own session.
    """
    mcp = FastMCP("compose-tools")

    @mcp.tool()
    def search_episodes(query: str, limit: int = 10) -> str:
        """Search episodes by keyword in summary."""
        session = session_factory()
        try:
            result = repo.search_episodes(session, query, limit)
            log_tool_call(session, STAGE, "search_episodes", {"query": query, "limit": limit}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def get_episode_detail(episode_id: int) -> str:
        """Get full details of a specific episode by ID."""
        session = session_factory()
        try:
            result = repo.get_episode_detail(session, episode_id) or {"error": f"Episode {episode_id} not found"}
            log_tool_call(session, STAGE, "get_episode_detail", {"episode_id": episode_id}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def get_all_playbook_entries() -> str:
        """List all current playbook entries (atomic behaviors)."""
        session = session_factory()
        try:
            result = repo.get_all_playbook_entries(session)
            log_tool_call(session, STAGE, "get_all_playbook_entries", {}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def get_all_routines() -> str:
        """List all current routines."""
        session = session_factory()
        try:
            result = repo.get_all_routines(session)
            log_tool_call(session, STAGE, "get_all_routines", {}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def write_routine(
        name: str, trigger: str, goal: str,
        steps: str, uses: str, confidence: float, maturity: str,
    ) -> str:
        """Create or update a routine."""
        session = session_factory()
        try:
            repo.write_routine(session, name, trigger, goal, steps, uses, confidence, maturity)
            session.commit()
            result = {"status": "ok", "name": name}
            log_tool_call(session, STAGE, "write_routine", {"name": name, "confidence": confidence}, result)
            return json.dumps(result)
        finally:
            session.close()

    return mcp
