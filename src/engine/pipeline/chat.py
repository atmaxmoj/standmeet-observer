"""Chat pipeline — tool dispatch, streaming orchestration, proposal execution.

Handles both OAuth (Agent SDK + MCP) and direct API (native tool_use) paths.
"""

import asyncio
import json
import logging
import os
import queue
import re
from collections.abc import AsyncGenerator
from typing import Any

from engine.config import MODEL_FAST, TOKEN_COSTS
from engine.observability.logger import log_mutation
from engine.prompts.chat import SYSTEM_PROMPT, TOOL_LABELS
from engine.storage.memory_file import write_playbook, delete_playbook

logger = logging.getLogger(__name__)

_THINKING_RE = re.compile(r"</?thinking>", re.IGNORECASE)


def clean_reply(text: str) -> str:
    """Strip leaked thinking tags from LLM output."""
    return _THINKING_RE.sub("", text).strip()


def sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ── Tool definitions (for native API path) ──


def make_read_tools(db) -> list[dict]:
    """Build Anthropic API tool definitions for read-only operations."""
    return [
        {
            "name": "search_episodes",
            "description": "Search episodes by keyword in summary or app names.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_recent_episodes",
            "description": "Get episodes from the last N days.",
            "input_schema": {
                "type": "object",
                "properties": {"days": {"type": "integer", "default": 7}},
                "required": [],
            },
        },
        {
            "name": "get_playbooks",
            "description": "Get all playbook entries, optionally filtered by search.",
            "input_schema": {
                "type": "object",
                "properties": {"search": {"type": "string", "default": ""}},
                "required": [],
            },
        },
        {
            "name": "get_playbook_history",
            "description": "Get confidence history for a specific playbook entry.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Playbook entry name (kebab-case)"},
                },
                "required": ["name"],
            },
        },
        {
            "name": "get_frames",
            "description": "Get recent screen capture frames with OCR text.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                    "search": {"type": "string", "default": ""},
                },
                "required": [],
            },
        },
        {
            "name": "get_audio",
            "description": "Get recent audio transcriptions.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                    "search": {"type": "string", "default": ""},
                },
                "required": [],
            },
        },
        {
            "name": "get_os_events",
            "description": "Get OS events (shell commands, browser URLs).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                    "event_type": {"type": "string", "default": "",
                                   "description": "Filter: shell_command or browser_url"},
                    "search": {"type": "string", "default": ""},
                },
                "required": [],
            },
        },
        {
            "name": "get_usage",
            "description": "Get API usage and cost summary.",
            "input_schema": {
                "type": "object",
                "properties": {"days": {"type": "integer", "default": 7}},
                "required": [],
            },
        },
        {
            "name": "web_search",
            "description": "Search the web for information. Use this to look up tools, techniques, "
            "best practices, or context mentioned in the observation data.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
        {
            "name": "propose_delete",
            "description": "Propose deleting records. Returns a proposal for user approval.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string",
                              "enum": ["episodes", "playbook_entries", "frames", "audio_frames", "os_events"]},
                    "ids": {"type": "array", "items": {"type": "integer"}, "description": "IDs to delete"},
                    "reason": {"type": "string", "description": "Why these should be deleted"},
                },
                "required": ["table", "ids", "reason"],
            },
        },
        {
            "name": "propose_update_playbook",
            "description": "Propose updating a playbook entry. Returns a proposal for user approval.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Playbook entry name"},
                    "context": {"type": "string"},
                    "action": {"type": "string"},
                    "confidence": {"type": "number"},
                    "maturity": {"type": "string", "enum": ["nascent", "developing", "mature", "mastered"]},
                    "reason": {"type": "string", "description": "Why this change is proposed"},
                },
                "required": ["name", "reason"],
            },
        },
    ]


# ── Web search ──


async def web_search(search_query: str, max_results: int = 5) -> list[dict]:
    """Search the web using Claude Code's built-in WebSearch."""
    try:
        from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions, ResultMessage

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
            env.pop("ANTHROPIC_API_KEY", None)

        prompt = (
            f"Search the web for: {search_query}\n\n"
            f"Return the top {max_results} results as a JSON array with fields: title, url, snippet.\n"
            f"Output ONLY the JSON array."
        )

        result_text = ""
        async for msg in sdk_query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                model="claude-haiku-4-5-20251001",
                max_turns=3,
                permission_mode="bypassPermissions",
                env=env,
            ),
        ):
            if isinstance(msg, ResultMessage):
                result_text = msg.result or ""

        if not result_text.strip():
            return [{"error": "Empty response from search"}]

        text = result_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            results = json.loads(match.group())
            if isinstance(results, list):
                return results[:max_results]

        return [{"title": "Search result", "url": "", "snippet": text[:500]}]
    except Exception as e:
        logger.warning("web_search failed: %s", e)
        return [{"error": str(e)}]


# ── Tool handlers ──


async def read_tool(db, name: str, args: dict) -> Any:
    """Execute a read-only tool. Returns result or None if not a read tool."""
    if name == "web_search":
        return await web_search(args["query"], args.get("max_results", 5))

    handlers = {
        "search_episodes": lambda: db.search_episodes_by_keyword(args["query"], args.get("limit", 10)),
        "get_recent_episodes": lambda: db.get_recent_episodes(args.get("days", 7)),
        "get_playbooks": lambda: db.get_all_playbooks(args.get("search", "")),
        "get_playbook_history": lambda: db.get_playbook_history(args["name"]),
        "get_usage": lambda: db.get_usage_summary(args.get("days", 7)),
    }
    if name in handlers:
        return await handlers[name]()

    paged = {
        "get_frames": lambda: db.get_frames(limit=args.get("limit", 20), search=args.get("search", "")),
        "get_audio": lambda: db.get_audio_frames(limit=args.get("limit", 20), search=args.get("search", "")),
        "get_os_events": lambda: db.get_os_events(
            limit=args.get("limit", 20), event_type=args.get("event_type", ""), search=args.get("search", ""),
        ),
    }
    if name in paged:
        rows, _ = await paged[name]()
        return rows
    return None


async def handle_tool(db, name: str, args: dict) -> tuple[Any, dict | None]:
    """Execute a tool call. Returns (result, proposal_or_none)."""
    result = await read_tool(db, name, args)
    if result is not None:
        return result, None

    ack = {"status": "proposal_created", "message": "Proposed. Waiting for user approval."}
    if name == "propose_delete":
        return ack, {"type": "delete", "table": args["table"], "ids": args["ids"], "reason": args["reason"]}
    if name == "propose_update_playbook":
        fields = {k: v for k, v in args.items() if k != "reason" and v is not None}
        return ack, {"type": "update_playbook", "fields": fields, "reason": args["reason"]}

    return {"error": f"Unknown tool: {name}"}, None


# ── Proposal execution ──


@log_mutation("chat_delete")
async def exec_delete(db, table: str, ids: list[int]) -> dict:
    """Execute delete, verify rows gone."""
    try:
        deleted = await db.delete_rows(table, ids)
    except ValueError as e:
        return {"success": False, "result": {"error": str(e)}}

    still_exist = []
    for row_id in ids:
        if await db.row_exists(table, row_id):
            still_exist.append(row_id)

    if still_exist:
        return {"success": False, "result": {"error": f"Rows still exist after delete: {still_exist}"}}

    if table == "playbook_entries":
        for row_id in ids:
            delete_playbook(str(row_id))

    return {"success": True, "result": {"deleted": deleted, "table": table, "ids": ids}}


@log_mutation("chat_update_playbook")
async def exec_update_playbook(db, fields: dict) -> dict:
    """Execute playbook update, verify fields changed, write memory file."""
    name = fields.get("name")
    if not name:
        return {"success": False, "result": {"error": "Missing playbook name in fields"}}

    playbooks = await db.get_all_playbooks()
    existing = next((p for p in playbooks if p["name"] == name), None)
    if not existing:
        return {"success": False, "result": {
            "error": f"Playbook '{name}' not found. Available: {[p['name'] for p in playbooks]}",
        }}

    await db.upsert_playbook(
        name=name,
        context=fields.get("context", existing["context"]),
        action=fields.get("action", existing["action"]),
        confidence=fields.get("confidence", existing["confidence"]),
        evidence=existing["evidence"],
        maturity=fields.get("maturity", existing["maturity"]),
    )

    playbooks_after = await db.get_all_playbooks()
    updated = next((p for p in playbooks_after if p["name"] == name), None)
    if not updated:
        return {"success": False, "result": {"error": f"Playbook '{name}' disappeared after update"}}

    changes = {}
    for key, val in fields.items():
        if key == "name":
            continue
        actual = updated.get(key)
        if actual != val:
            return {"success": False, "result": {"error": f"Field '{key}' not updated: expected {val}, got {actual}"}}
        changes[key] = {"before": existing.get(key), "after": val}

    file_path = write_playbook(updated)
    return {"success": True, "result": {"name": name, "changes": changes, "file": str(file_path)}}


# ── Usage tracking ──


async def record_usage(db, input_tokens: int, output_tokens: int):
    """Record chat usage to token_usage table."""
    costs = TOKEN_COSTS.get(MODEL_FAST, {})
    cost = input_tokens * costs.get("input", 0) + output_tokens * costs.get("output", 0)
    await db.record_usage(
        model=MODEL_FAST, layer="chat",
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost,
    )


# ── Streaming orchestration ──


def build_chat_prompt(messages: list[dict]) -> str:
    """Build a single prompt from system prompt + conversation history."""
    parts = [SYSTEM_PROMPT]
    for m in messages:
        role = m["role"]
        content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
        parts.append(f"[{role}]: {content}")
    return "\n\n".join(parts)


async def chat_stream(db, settings, messages: list[dict], *, agent=None) -> AsyncGenerator[str, None]:
    """SSE stream generator for chat.

    Creates AgentService from settings. Routes to MCP (OAuth) or native (API key).
    agent override is for testing only.
    """
    if agent is None:
        from engine.agents.service import AgentService
        agent = AgentService(settings)
    logger.info("chat: starting with %d messages, sdk=%s", len(messages), agent.uses_sdk)

    if agent.uses_sdk:
        async for s in _stream_mcp(db, agent, messages):
            yield s
    else:
        async for s in _stream_native(db, agent, messages):
            yield s


async def _stream_mcp(db, agent, messages: list[dict]) -> AsyncGenerator[str, None]:
    """Chat via Agent SDK + MCP tools (OAuth path)."""
    from engine.agents.tools.chat_mcp import create_chat_mcp_server
    from engine.storage.engine import get_sync_session_factory

    sync_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not sync_url:
        yield sse("error", {"message": "DATABASE_URL_SYNC not configured"})
        return

    session = get_sync_session_factory(sync_url)()
    try:
        tool_queue: queue.Queue[str | None] = queue.Queue()
        mcp_server = create_chat_mcp_server(
            session, on_tool_call=lambda name: tool_queue.put(name),
        )
        prompt = build_chat_prompt(messages)
        yield sse("tool_call", {"name": "thinking", "label": "Thinking..."})

        def _run():
            result = agent.run_with_mcp(
                prompt=prompt, mcp_server=mcp_server, mcp_name="chat",
                stage="chat", session=session, model=MODEL_FAST, max_turns=10,
            )
            tool_queue.put(None)
            return result

        future = asyncio.get_event_loop().run_in_executor(None, _run)

        while True:
            try:
                name = await asyncio.to_thread(tool_queue.get, timeout=0.5)
                if name is None:
                    break
                logger.info("chat(mcp): tool %s", name)
                yield sse("tool_call", {"name": name, "label": TOOL_LABELS.get(name, name)})
            except Exception:
                if future.done():
                    break

        result = await future
        reply = clean_reply(result.result_text)
        await db.append_chat_message("assistant", reply, json.dumps([], default=str))
        await record_usage(db, result.input_tokens, result.output_tokens)
        logger.info("chat(mcp): done, %d in, %d out", result.input_tokens, result.output_tokens)
        yield sse("text", {"content": reply, "proposals": [],
                           "input_tokens": result.input_tokens, "output_tokens": result.output_tokens})
    except Exception as e:
        logger.exception("chat(mcp): failed")
        yield sse("error", {"message": f"Chat failed: {e}"})
    finally:
        session.close()


async def _stream_native(db, agent, messages: list[dict]) -> AsyncGenerator[str, None]:
    """Chat via native API with tool_use blocks (DirectAPIClient path)."""
    tools = make_read_tools(db)
    proposals: list[dict] = []

    def _make_handler(tool_name):
        async def handler(**kwargs):
            result, proposal = await handle_tool(db, tool_name, kwargs)
            if proposal:
                proposals.append(proposal)
            return result
        return handler

    tool_handlers = {t["name"]: _make_handler(t["name"]) for t in tools}

    async for event in agent.astream(
        messages=messages, model=MODEL_FAST, tools=tools,
        tool_handlers=tool_handlers, system=SYSTEM_PROMPT,
    ):
        if event["type"] == "tool_call":
            label = TOOL_LABELS.get(event["name"], event["name"])
            logger.info("chat: tool %s", event["name"])
            yield sse("tool_call", {"name": event["name"], "label": label})

        elif event["type"] == "response":
            text_blocks = [b for b in event["content"] if b.type == "text"]
            reply = clean_reply(text_blocks[-1].text if text_blocks else "")
            total_input = event["input_tokens"]
            total_output = event["output_tokens"]

            await db.append_chat_message("assistant", reply, json.dumps(proposals, default=str))
            await record_usage(db, total_input, total_output)
            logger.info("chat: done, %d in, %d out, %d proposals", total_input, total_output, len(proposals))
            yield sse("text", {"content": reply, "proposals": proposals,
                               "input_tokens": total_input, "output_tokens": total_output})

        elif event["type"] == "error":
            yield sse("error", {"message": event["message"]})
