"""In-process MCP server for chat tool calling via Agent SDK."""

import json

from sqlalchemy.orm import Session
from mcp.server.fastmcp import FastMCP

from engine.agents import repository as repo


def create_chat_mcp_server(session: Session) -> FastMCP:
    """Create an in-process MCP server with chat read tools."""
    mcp = FastMCP("chat-tools")

    @mcp.tool()
    def search_episodes(query: str, limit: int = 10) -> str:
        """Search episodes by keyword in summary."""
        return json.dumps(repo.search_episodes(session, query, limit), default=str)

    @mcp.tool()
    def get_recent_episodes(days: int = 7) -> str:
        """Get recent episodes from the last N days."""
        return json.dumps(repo.get_recent_episodes(session, hours=days * 24), default=str)

    @mcp.tool()
    def get_playbooks(search: str = "") -> str:
        """Get all playbook entries, optionally filtered by search."""
        entries = repo.get_all_playbook_entries(session)
        if search:
            search_lower = search.lower()
            entries = [e for e in entries if search_lower in json.dumps(e).lower()]
        return json.dumps(entries, default=str)

    @mcp.tool()
    def get_playbook_history(name: str) -> str:
        """Get version history of a specific playbook entry."""
        return json.dumps(repo.get_playbook_history(session, name), default=str)

    @mcp.tool()
    def get_usage(days: int = 7) -> str:
        """Get token usage and cost summary."""
        return json.dumps(repo.get_data_stats(session), default=str)

    @mcp.tool()
    def get_routines(search: str = "") -> str:
        """Get all routines."""
        routines = repo.get_all_routines(session)
        if search:
            search_lower = search.lower()
            routines = [r for r in routines if search_lower in json.dumps(r).lower()]
        return json.dumps(routines, default=str)

    @mcp.tool()
    def get_frames(limit: int = 20, search: str = "") -> str:
        """Get recent screen capture frames."""
        return json.dumps(repo.get_recent_frames(session, limit=limit), default=str)

    @mcp.tool()
    def get_os_events(limit: int = 20, event_type: str = "", search: str = "") -> str:
        """Get recent OS events (app launch, quit, sleep, wake)."""
        if event_type:
            return json.dumps(repo.get_os_events_by_type(session, event_type, limit), default=str)
        return json.dumps(repo.get_recent_os_events(session, limit=limit), default=str)

    return mcp
