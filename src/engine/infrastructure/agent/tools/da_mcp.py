"""SDK MCP tools for agentic L4 DA (Personal Data Analyst).

Uses Agent SDK's native @tool + create_sdk_mcp_server.
"""

import json

from sqlalchemy.orm import sessionmaker

from claude_agent_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig
from engine.infrastructure.observability.logger import log_tool_call
from engine.infrastructure.agent import repository as repo

STAGE = "da_agentic"


def create_da_mcp_server(session_factory: sessionmaker) -> McpSdkServerConfig:
    """Create an SDK MCP server with DA read + write tools."""
    tools = (_episode_tools(session_factory) + _memory_tools(session_factory)
             + _da_tools(session_factory) + _write_tools(session_factory))
    return create_sdk_mcp_server(name="da-tools", tools=tools)


def _episode_tools(session_factory: sessionmaker) -> list:
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

    @tool("get_recent_episodes", "Get episodes from the last N days.", {
        "days": int,
    })
    async def get_recent_episodes(args):
        session = session_factory()
        try:
            result = repo.get_recent_episodes(session, hours=args.get("days", 7) * 24)
            log_tool_call(session, STAGE, "get_recent_episodes", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    return [search_episodes, get_episode_detail, get_recent_episodes]


def _memory_tools(session_factory: sessionmaker) -> list:
    @tool("get_all_playbook_entries", "List all current playbook entries (behavioral patterns).", {})
    async def get_all_playbook_entries(args):
        session = session_factory()
        try:
            result = repo.get_all_playbook_entries(session)
            log_tool_call(session, STAGE, "get_all_playbook_entries", args, result)
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

    @tool("get_all_routines", "List all current routines (multi-step workflows).", {})
    async def get_all_routines(args):
        session = session_factory()
        try:
            result = repo.get_all_routines(session)
            log_tool_call(session, STAGE, "get_all_routines", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("get_data_stats", "Get row counts for all data tables.", {})
    async def get_data_stats(args):
        session = session_factory()
        try:
            result = repo.get_data_stats(session)
            log_tool_call(session, STAGE, "get_data_stats", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    return [get_all_playbook_entries, get_playbook_history, get_all_routines, get_data_stats]


def _da_tools(session_factory: sessionmaker) -> list:
    @tool("get_previous_insights", "Get your own previous insights to avoid repetition.", {
        "limit": int,
    })
    async def get_previous_insights(args):
        session = session_factory()
        try:
            result = repo.get_previous_insights(session, args.get("limit", 20))
            log_tool_call(session, STAGE, "get_previous_insights", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("get_da_goals", "Get your analytical goals (active, completed, retired).", {})
    async def get_da_goals(args):
        session = session_factory()
        try:
            result = repo.get_da_goals(session)
            log_tool_call(session, STAGE, "get_da_goals", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    return [get_previous_insights, get_da_goals]


def _write_tools(session_factory: sessionmaker) -> list:
    @tool("write_insight", "Save an insight. Every insight MUST cite evidence. Optionally include structured data (JSON) for charts.", {
        "title": str, "body": str, "category": str, "evidence": str, "run_id": str, "data": str,
    })
    async def write_insight(args):
        session = session_factory()
        try:
            result = repo.write_insight(
                session, args["title"], args["body"], args["category"],
                args["evidence"], args["run_id"], args.get("data", ""),
            )
            session.commit()
            log_tool_call(session, STAGE, "write_insight", {"title": args["title"]}, result)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        finally:
            session.close()

    @tool("write_da_goal", "Create a new analytical goal to track across runs.", {
        "goal": str,
    })
    async def write_da_goal(args):
        session = session_factory()
        try:
            result = repo.write_da_goal(session, args["goal"])
            session.commit()
            log_tool_call(session, STAGE, "write_da_goal", {"goal": args["goal"][:60]}, result)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        finally:
            session.close()

    @tool("update_da_goal", "Update an existing goal's status or add progress notes.", {
        "goal_id": int, "status": str, "progress_note": str,
    })
    async def update_da_goal(args):
        session = session_factory()
        try:
            result = repo.update_da_goal(
                session, args["goal_id"], args.get("status", ""),
                args.get("progress_note", ""),
            )
            session.commit()
            log_tool_call(session, STAGE, "update_da_goal", {"goal_id": args["goal_id"]}, result)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        finally:
            session.close()

    return [write_insight, write_da_goal, update_da_goal]
