"""SDK MCP tools for chat tool calling via Agent SDK.

Uses claude_agent_sdk @tool + create_sdk_mcp_server (same as distill/compose).
"""

import json
from collections.abc import Callable

from sqlalchemy.orm import Session

from claude_agent_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig
from engine.infrastructure.agent import repository as repo


def create_chat_mcp_server(
    session: Session,
    on_tool_call: Callable[[str], None] | None = None,
) -> McpSdkServerConfig:
    """Create an SDK MCP server with chat read tools.

    on_tool_call is invoked when each tool is called,
    enabling real-time throbbing in the UI.
    """

    def _notify(name: str):
        if on_tool_call:
            on_tool_call(name)

    tools = _memory_tools(session, _notify) + _capture_tools(session, _notify)
    return create_sdk_mcp_server(name="chat-tools", tools=tools)


def _memory_tools(session: Session, notify: Callable[[str], None]) -> list:
    @tool("search_episodes", "Search episodes by keyword in summary.", {
        "query": str, "limit": int,
    })
    async def search_episodes(args):
        notify("search_episodes")
        result = repo.search_episodes(session, args["query"], args.get("limit", 10))
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    @tool("get_recent_episodes", "Get recent episodes from the last N days.", {
        "days": int,
    })
    async def get_recent_episodes(args):
        notify("get_recent_episodes")
        result = repo.get_recent_episodes(session, hours=args.get("days", 7) * 24)
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    @tool("get_episodes_by_app", "Get episodes filtered by app name.", {
        "app_name": str, "limit": int,
    })
    async def get_episodes_by_app(args):
        notify("get_episodes_by_app")
        result = repo.get_episodes_by_app(session, args["app_name"], args.get("limit", 10))
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    @tool("get_playbooks", "Get all playbook entries, optionally filtered by search.", {
        "search": str,
    })
    async def get_playbooks(args):
        notify("get_playbooks")
        entries = repo.get_all_playbook_entries(session)
        search = args.get("search", "")
        if search:
            search_lower = search.lower()
            entries = [e for e in entries if search_lower in json.dumps(e).lower()]
        return {"content": [{"type": "text", "text": json.dumps(entries, default=str)}]}

    @tool("get_playbook_history", "Get version history of a specific playbook entry.", {
        "name": str,
    })
    async def get_playbook_history(args):
        notify("get_playbook_history")
        result = repo.get_playbook_history(session, args["name"])
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    @tool("get_stale_entries", "Find playbook entries with no recent evidence.", {
        "days": int,
    })
    async def get_stale_entries(args):
        notify("get_stale_entries")
        result = repo.get_stale_entries(session, args.get("days", 14))
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    @tool("get_similar_entries", "Find playbook entries with similar names (word overlap).", {
        "name": str,
    })
    async def get_similar_entries(args):
        notify("get_similar_entries")
        result = repo.get_similar_entries(session, args["name"])
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    @tool("get_routines", "Get all routines, optionally filtered by search.", {
        "search": str,
    })
    async def get_routines(args):
        notify("get_routines")
        routines = repo.get_all_routines(session)
        search = args.get("search", "")
        if search:
            search_lower = search.lower()
            routines = [r for r in routines if search_lower in json.dumps(r).lower()]
        return {"content": [{"type": "text", "text": json.dumps(routines, default=str)}]}

    @tool("get_usage", "Get token usage and cost summary.", {})
    async def get_usage(args):
        notify("get_usage")
        result = repo.get_data_stats(session)
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    return [search_episodes, get_recent_episodes, get_episodes_by_app,
            get_playbooks, get_playbook_history, get_stale_entries,
            get_similar_entries, get_routines, get_usage]


def _capture_tools(session: Session, notify: Callable[[str], None]) -> list:
    @tool("get_frames", "Get recent screen capture frames, optionally filtered by app.", {
        "limit": int, "app_name": str,
    })
    async def get_frames(args):
        notify("get_frames")
        app_name = args.get("app_name", "")
        limit = args.get("limit", 20)
        if app_name:
            result = repo.get_frames_by_app(session, app_name, limit)
        else:
            result = repo.get_recent_frames(session, limit=limit)
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    @tool("get_audio", "Get recent audio transcriptions.", {
        "days": int, "limit": int,
    })
    async def get_audio(args):
        notify("get_audio")
        result = repo.get_recent_audio(session, hours=args.get("days", 7) * 24, limit=args.get("limit", 20))
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    @tool("get_os_events", "Get recent OS events (app launch, quit, sleep, wake).", {
        "limit": int, "event_type": str,
    })
    async def get_os_events(args):
        notify("get_os_events")
        event_type = args.get("event_type", "")
        limit = args.get("limit", 20)
        if event_type:
            result = repo.get_os_events_by_type(session, event_type, limit)
        else:
            result = repo.get_recent_os_events(session, limit=limit)
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    return [get_frames, get_audio, get_os_events]
