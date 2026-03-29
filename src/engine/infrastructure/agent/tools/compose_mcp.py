"""SDK MCP tools for agentic L3 routine composition.

Uses Agent SDK's native @tool + create_sdk_mcp_server.
"""

import json

from sqlalchemy.orm import sessionmaker

from claude_agent_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig
from engine.infrastructure.observability.logger import log_tool_call
from engine.infrastructure.agent import repository as repo

STAGE = "compose_agentic"


def create_compose_mcp_server(session_factory: sessionmaker) -> McpSdkServerConfig:
    """Create an SDK MCP server with routine composition tools."""

    @tool("search_episodes", "Search episodes by keyword in summary.", {
        "query": str, "limit": int,
    })
    async def search_episodes(args):
        session = session_factory()
        try:
            result = repo.search_episodes(session, args["query"], args.get("limit", 10))
            log_tool_call(session, STAGE, "search_episodes", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("get_episode_detail", "Get full details of a specific episode by ID.", {
        "episode_id": int,
    })
    async def get_episode_detail(args):
        session = session_factory()
        try:
            result = repo.get_episode_detail(session, args["episode_id"])
            result = result or {"error": f"Episode {args['episode_id']} not found"}
            log_tool_call(session, STAGE, "get_episode_detail", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("get_all_playbook_entries", "List all current playbook entries (atomic behaviors).", {})
    async def get_all_playbook_entries(args):
        session = session_factory()
        try:
            result = repo.get_all_playbook_entries(session)
            log_tool_call(session, STAGE, "get_all_playbook_entries", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("get_all_routines", "List all current routines.", {})
    async def get_all_routines(args):
        session = session_factory()
        try:
            result = repo.get_all_routines(session)
            log_tool_call(session, STAGE, "get_all_routines", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("write_routine", "Create or update a routine.", {
        "name": str, "trigger": str, "goal": str,
        "steps": str, "uses": str, "confidence": float, "maturity": str,
    })
    async def write_routine(args):
        session = session_factory()
        try:
            repo.write_routine(
                session, args["name"], args["trigger"], args["goal"],
                args["steps"], args["uses"], args["confidence"], args["maturity"],
            )
            session.commit()
            result = {"status": "ok", "name": args["name"]}
            log_tool_call(session, STAGE, "write_routine", {"name": args["name"]}, result)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        finally:
            session.close()

    return create_sdk_mcp_server(
        name="compose-tools",
        tools=[search_episodes, get_episode_detail, get_all_playbook_entries,
               get_all_routines, write_routine],
    )
