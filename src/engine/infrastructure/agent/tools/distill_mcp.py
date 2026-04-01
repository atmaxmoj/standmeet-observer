"""SDK MCP tools for agentic L2 distillation.

Uses Agent SDK's native @tool + create_sdk_mcp_server for reliable
in-process MCP transport (avoids FastMCP "Stream closed" issues).
"""

import json

from sqlalchemy.orm import sessionmaker

from claude_agent_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig
from engine.infrastructure.observability.logger import log_tool_call
from engine.infrastructure.agent import repository as repo

STAGE = "distill_agentic"


def create_distill_mcp_server(session_factory: sessionmaker) -> McpSdkServerConfig:
    """Create an SDK MCP server with distill tools."""
    tools = _read_tools(session_factory) + _write_tools(session_factory)
    return create_sdk_mcp_server(name="distill-tools", tools=tools)


def _read_tools(session_factory: sessionmaker) -> list:
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

    @tool("get_episode_frames", "Get raw capture frames for an episode to verify patterns.", {
        "episode_id": int, "limit": int,
    })
    async def get_episode_frames(args):
        session = session_factory()
        try:
            result = repo.get_episode_frames(session, args["episode_id"], args.get("limit", 10))
            log_tool_call(session, STAGE, "get_episode_frames", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("get_playbook_history", "Get confidence/maturity history for a playbook entry.", {
        "name": str,
    })
    async def get_playbook_history(args):
        session = session_factory()
        try:
            result = repo.get_playbook_history(session, args["name"])
            log_tool_call(session, STAGE, "get_playbook_history", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("get_all_playbook_entries", "List all current playbook entries.", {})
    async def get_all_playbook_entries(args):
        session = session_factory()
        try:
            result = repo.get_all_playbook_entries(session)
            log_tool_call(session, STAGE, "get_all_playbook_entries", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("get_da_insights", "Get recent DA insights to reference during distillation.", {
        "limit": int,
    })
    async def get_da_insights(args):
        session = session_factory()
        try:
            result = repo.get_previous_insights(session, args.get("limit", 10))
            log_tool_call(session, STAGE, "get_da_insights", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    return [search_episodes, get_episode_detail, get_episode_frames,
            get_playbook_history, get_all_playbook_entries, get_da_insights]


def _write_tools(session_factory: sessionmaker) -> list:
    @tool("write_playbook_entry", "Create or update a playbook entry.", {
        "name": str, "context": str, "action": str,
        "confidence": float, "maturity": str, "evidence": str,
    })
    async def write_playbook_entry(args):
        session = session_factory()
        try:
            repo.write_playbook_entry(
                session, args["name"], args["context"], args["action"],
                args["confidence"], args["maturity"], args["evidence"],
            )
            session.commit()
            result = {"status": "ok", "name": args["name"]}
            log_tool_call(session, STAGE, "write_playbook_entry", {"name": args["name"]}, result)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        finally:
            session.close()

    return [write_playbook_entry]
