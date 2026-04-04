"""SDK MCP tools for Scrum Master — project task tracking.

Uses Agent SDK's native @tool + create_sdk_mcp_server.
"""

import json

from sqlalchemy.orm import sessionmaker

from claude_agent_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig
from engine.infrastructure.observability.logger import log_tool_call
from engine.infrastructure.agent import repository as repo

STAGE = "scm_agentic"


def create_scm_mcp_server(session_factory: sessionmaker) -> McpSdkServerConfig:
    """Create an SDK MCP server with Scrum Master tools."""
    tools = _read_tools(session_factory) + _task_tools(session_factory)
    return create_sdk_mcp_server(name="scm-tools", tools=tools)


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


def _task_tools(session_factory: sessionmaker) -> list:
    @tool("get_scm_tasks", "Get current task board. Optionally filter by status.", {
        "status": str,
    })
    async def get_scm_tasks(args):
        session = session_factory()
        try:
            result = repo.get_scm_tasks(session, args.get("status", ""))
            log_tool_call(session, STAGE, "get_scm_tasks", args, result)
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
        finally:
            session.close()

    @tool("write_scm_task", "Create a new task on the board.", {
        "project": str, "title": str, "status": str, "evidence": str, "run_id": str,
    })
    async def write_scm_task(args):
        session = session_factory()
        try:
            result = repo.write_scm_task(
                session, args["project"], args["title"], args["status"],
                args["evidence"], args["run_id"],
            )
            session.commit()
            log_tool_call(session, STAGE, "write_scm_task", {"project": args["project"], "title": args["title"]}, result)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        finally:
            session.close()

    @tool("update_scm_task", "Update a task's status or add a note.", {
        "task_id": int, "status": str, "note": str,
    })
    async def update_scm_task(args):
        session = session_factory()
        try:
            result = repo.update_scm_task(
                session, args["task_id"], args.get("status", ""),
                args.get("note", ""),
            )
            session.commit()
            log_tool_call(session, STAGE, "update_scm_task", {"task_id": args["task_id"]}, result)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        finally:
            session.close()

    return [get_scm_tasks, write_scm_task, update_scm_task]
