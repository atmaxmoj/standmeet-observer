"""In-process MCP server for agentic L2 distillation.

Each tool call creates its own DB session to avoid concurrency issues
when the Agent SDK dispatches parallel tool calls.
"""

import json

from sqlalchemy.orm import sessionmaker
from mcp.server.fastmcp import FastMCP

from engine.infrastructure.observability.logger import log_tool_call
from engine.infrastructure.agent import repository as repo

STAGE = "distill_agentic"


def create_distill_mcp_server(session_factory: sessionmaker) -> FastMCP:
    """Create an in-process MCP server with distill tools.

    Args:
        session_factory: SQLAlchemy session factory — each tool call gets its own session.
    """
    mcp = FastMCP("distill-tools")
    _register_read_tools(mcp, session_factory)
    _register_write_tools(mcp, session_factory)
    return mcp


def _register_read_tools(mcp: FastMCP, session_factory: sessionmaker):
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
    def get_episode_frames(episode_id: int, limit: int = 10) -> str:
        """Get raw capture frames for an episode to verify patterns."""
        session = session_factory()
        try:
            result = repo.get_episode_frames(session, episode_id, limit)
            log_tool_call(session, STAGE, "get_episode_frames", {"episode_id": episode_id}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def get_playbook_history(name: str) -> str:
        """Get confidence/maturity history for a playbook entry."""
        session = session_factory()
        try:
            result = repo.get_playbook_history(session, name)
            log_tool_call(session, STAGE, "get_playbook_history", {"name": name}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()

    @mcp.tool()
    def get_all_playbook_entries() -> str:
        """List all current playbook entries."""
        session = session_factory()
        try:
            result = repo.get_all_playbook_entries(session)
            log_tool_call(session, STAGE, "get_all_playbook_entries", {}, result)
            return json.dumps(result, default=str)
        finally:
            session.close()


def _register_write_tools(mcp: FastMCP, session_factory: sessionmaker):
    @mcp.tool()
    def write_playbook_entry(
        name: str, context: str, action: str,
        confidence: float, maturity: str, evidence: str,
    ) -> str:
        """Create or update a playbook entry."""
        session = session_factory()
        try:
            repo.write_playbook_entry(session, name, context, action, confidence, maturity, evidence)
            session.commit()
            result = {"status": "ok", "name": name}
            log_tool_call(session, STAGE, "write_playbook_entry", {"name": name, "confidence": confidence}, result)
            return json.dumps(result)
        finally:
            session.close()
