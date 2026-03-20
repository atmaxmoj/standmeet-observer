"""Memory chat endpoint — agent with read tools + mutation proposals.

Uses SSE streaming so the frontend can show tool-use throbbing in real time.
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from engine.config import MODEL_FAST
from engine.observability.logger import log_mutation
from engine.storage.memory_file import write_playbook, delete_playbook

logger = logging.getLogger(__name__)

router = APIRouter()

_THINKING_RE = None


def _clean_reply(text: str) -> str:
    """Strip leaked thinking tags from LLM output."""
    import re
    global _THINKING_RE  # noqa: PLW0603
    if _THINKING_RE is None:
        _THINKING_RE = re.compile(r"</?thinking>", re.IGNORECASE)
    return _THINKING_RE.sub("", text).strip()

# Nice labels for tool names shown in the UI
TOOL_LABELS = {
    "search_episodes": "Searching episodes",
    "get_recent_episodes": "Getting recent episodes",
    "get_playbooks": "Getting playbooks",
    "get_playbook_history": "Getting playbook history",
    "get_frames": "Getting frames",
    "get_audio": "Getting audio",
    "get_os_events": "Getting OS events",
    "get_usage": "Getting usage stats",
    "web_search": "Searching the web",
    "propose_delete": "Proposing deletion",
    "propose_update_playbook": "Proposing playbook update",
}

SYSTEM_PROMPT = """You are the memory assistant for an observation system that captures screen activity, audio, shell commands, browser tabs, and system events. This data is distilled into episodes (task summaries) and playbook entries (behavioral patterns).

IMPORTANT: You have NO built-in knowledge of the user's data. You MUST use your tools to look up information before answering any question about the user's activity, episodes, playbooks, or routines. Never guess or fabricate answers — always query first.

Available data you can query:
- Episodes: task-level summaries of what the user did
- Playbooks: recurring behavioral patterns (when → then → because)
- Routines: multi-step sequences
- Frames: raw screen captures with OCR text
- Audio: transcriptions
- OS events: shell commands, browser URLs
- Usage: LLM cost tracking

You can also search the web for context when needed.

When the user asks to modify data (delete, update), use proposal tools. Proposals are shown to the user for approval before execution.

Be concise. Summarize insights, don't dump raw data."""


def _make_read_tools(db) -> list[dict]:
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
                "properties": {
                    "days": {"type": "integer", "default": 7},
                },
                "required": [],
            },
        },
        {
            "name": "get_playbooks",
            "description": "Get all playbook entries, optionally filtered by search.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "default": ""},
                },
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
                    "event_type": {"type": "string", "default": "", "description": "Filter: shell_command or browser_url"},
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
                "properties": {
                    "days": {"type": "integer", "default": 7},
                },
                "required": [],
            },
        },
        # -- Web search --
        {
            "name": "web_search",
            "description": "Search the web for information. Use this to look up tools, techniques, best practices, or context mentioned in the observation data.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
        # -- Mutation proposals (don't execute, return proposal for user approval) --
        {
            "name": "propose_delete",
            "description": "Propose deleting records. Returns a proposal for user approval. Use this when the user asks to delete episodes, playbook entries, frames, audio, or os_events.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": ["episodes", "playbook_entries", "frames", "audio_frames", "os_events"]},
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


async def _web_search(search_query: str, max_results: int = 5) -> list[dict]:
    """Search the web using Claude Code's built-in WebSearch.

    No separate search API key needed — uses the same OAuth token as the LLM.
    Makes a separate Agent SDK query() call with tools enabled.
    """
    try:
        import os
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
        search_log: list[dict] = []  # trace the full message flow

        async for msg in sdk_query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                model="claude-haiku-4-5-20251001",
                max_turns=3,
                permission_mode="bypassPermissions",
                env=env,
                # No tools=[] — let Claude Code use its built-in WebSearch
            ),
        ):
            msg_type = type(msg).__name__
            search_log.append({"type": msg_type, "data": str(msg)[:500]})
            logger.debug("web_search msg: %s %s", msg_type, str(msg)[:500])

            if isinstance(msg, ResultMessage):
                result_text = msg.result or ""

        logger.info("web_search trace: %d messages, types=%s",
                    len(search_log), [m["type"] for m in search_log])

        if not result_text.strip():
            return [{"error": "Empty response from search", "_trace": search_log}]

        # Parse results — handle markdown fences, extra text, etc.
        text = result_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        # Try to find JSON array in the response
        import re
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            results = json.loads(match.group())
            if isinstance(results, list):
                return results[:max_results]

        # If no JSON array found, return the raw text as a single result
        return [{"title": "Search result", "url": "", "snippet": text[:500]}]
    except Exception as e:
        logger.warning("web_search failed: %s", e)
        return [{"error": str(e)}]


async def _read_tool(db, name: str, args: dict) -> Any:
    """Execute a read-only tool. Returns result or None if not a read tool."""
    if name == "web_search":
        return await _web_search(args["query"], args.get("max_results", 5))

    handlers = {
        "search_episodes": lambda: db.search_episodes_by_keyword(args["query"], args.get("limit", 10)),
        "get_recent_episodes": lambda: db.get_recent_episodes(args.get("days", 7)),
        "get_playbooks": lambda: db.get_all_playbooks(args.get("search", "")),
        "get_playbook_history": lambda: db.get_playbook_history(args["name"]),
        "get_usage": lambda: db.get_usage_summary(args.get("days", 7)),
    }
    if name in handlers:
        return await handlers[name]()

    # Paginated read tools (return rows, total — we discard total)
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


async def _handle_tool(db, name: str, args: dict) -> tuple[Any, dict | None]:
    """Execute a tool call. Returns (result, proposal_or_none)."""
    # Read tools
    result = await _read_tool(db, name, args)
    if result is not None:
        return result, None

    # Proposal tools
    ack = {"status": "proposal_created", "message": "Proposed. Waiting for user approval."}
    if name == "propose_delete":
        proposal = {"type": "delete", "table": args["table"], "ids": args["ids"], "reason": args["reason"]}
        return ack, proposal
    if name == "propose_update_playbook":
        fields = {k: v for k, v in args.items() if k != "reason" and v is not None}
        return ack, {"type": "update_playbook", "fields": fields, "reason": args["reason"]}

    return {"error": f"Unknown tool: {name}"}, None


async def _record_usage(db, input_tokens: int, output_tokens: int):
    """Record chat usage to token_usage table."""
    from engine.config import TOKEN_COSTS, MODEL_FAST
    costs = TOKEN_COSTS.get(MODEL_FAST, {})
    cost = input_tokens * costs.get("input", 0) + output_tokens * costs.get("output", 0)
    await db.record_usage(
        model=MODEL_FAST, layer="chat",
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost,
    )


def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


class ChatRequest(BaseModel):
    messages: list[dict]


@router.get("/memory/chat/history")
async def chat_history(request: Request):
    db = request.app.state.db
    messages = await db.get_chat_messages()
    return {"messages": messages}


@router.delete("/memory/chat/history")
async def clear_chat_history(request: Request):
    db = request.app.state.db
    await db.clear_chat_messages()
    return {"cleared": True}


class ProposalExecution(BaseModel):
    type: str
    table: str | None = None
    ids: list[int] | None = None
    fields: dict | None = None
    reason: str = ""


@log_mutation("chat_delete")
async def _exec_delete(db, table: str, ids: list[int]) -> dict:
    """Execute delete, verify rows gone. Returns {success, result}."""
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

    # Delete memory files for playbook entries
    if table == "playbook_entries":
        for row_id in ids:
            delete_playbook(str(row_id))

    return {"success": True, "result": {"deleted": deleted, "table": table, "ids": ids}}


@log_mutation("chat_update_playbook")
async def _exec_update_playbook(db, fields: dict) -> dict:
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

    # Verify
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

    # Write memory file
    file_path = write_playbook(updated)
    return {"success": True, "result": {"name": name, "changes": changes, "file": str(file_path)}}


@router.post("/memory/chat/execute-proposal")
async def execute_proposal(request: Request, body: ProposalExecution):
    """Execute a proposal, verify the result, and log it."""
    db = request.app.state.db
    if body.type == "delete" and body.table and body.ids:
        return await _exec_delete(db, body.table, body.ids)
    if body.type == "update_playbook" and body.fields:
        return await _exec_update_playbook(db, body.fields)
    return {"success": False, "result": {"error": f"Unknown proposal type: {body.type}"}}


class ProposalStatusUpdate(BaseModel):
    message_id: int
    proposal_index: int
    status: str  # "approved" or "rejected"


@router.post("/memory/chat/proposal-status")
async def update_proposal_status(request: Request, body: ProposalStatusUpdate):
    """Persist proposal approval/rejection status to DB."""
    db = request.app.state.db
    messages = await db.get_chat_messages()
    msg = next((m for m in messages if m["id"] == body.message_id), None)
    if not msg:
        return {"error": "Message not found"}
    proposals = json.loads(msg["proposals"]) if isinstance(msg["proposals"], str) else msg["proposals"]
    if body.proposal_index >= len(proposals):
        return {"error": "Proposal index out of range"}
    proposals[body.proposal_index]["status"] = body.status
    await db.update_chat_proposals(body.message_id, json.dumps(proposals, default=str))
    return {"updated": True}


async def _chat_stream(db, llm, messages: list[dict]) -> AsyncGenerator[str, None]:
    """SSE stream generator for chat.

    DirectAPIClient: uses astream() with native tool_use blocks.
    AgentSDKClient: uses run_with_mcp() — Agent SDK handles tool calling via MCP.
    """
    from engine.llm.adapters.agent_sdk import AgentSDKClient

    logger.info("chat: starting with %d messages, llm=%s", len(messages), type(llm).__name__)

    if isinstance(llm, AgentSDKClient):
        async for sse in _chat_stream_mcp(db, llm, messages):
            yield sse
    else:
        async for sse in _chat_stream_native(db, llm, messages):
            yield sse


def _build_chat_prompt(messages: list[dict]) -> str:
    """Build a single prompt from system prompt + conversation history."""
    parts = [SYSTEM_PROMPT]
    for m in messages:
        role = m["role"]
        content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
        parts.append(f"[{role}]: {content}")
    return "\n\n".join(parts)


async def _chat_stream_mcp(db, llm, messages: list[dict]) -> AsyncGenerator[str, None]:
    """Chat via Agent SDK + MCP tools (OAuth path). Agent SDK handles tool calling natively."""
    import asyncio
    import os
    import queue

    from engine.agents.service import AgentService, MCPRunOptions
    from engine.agents.tools.chat_mcp import CHAT_TOOL_NAMES, create_chat_mcp_server
    from engine.storage.engine import get_sync_session_factory

    sync_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not sync_url:
        yield _sse("error", {"message": "DATABASE_URL_SYNC not configured"})
        return

    session = get_sync_session_factory(sync_url)()
    try:
        mcp_server = create_chat_mcp_server(session)
        prompt = _build_chat_prompt(messages)
        yield _sse("tool_call", {"name": "thinking", "label": "Thinking..."})

        tool_queue: queue.Queue[str | None] = queue.Queue()
        allowed = [f"mcp__chat__{n}" for n in CHAT_TOOL_NAMES] + ["WebSearch"]

        def _run():
            result = AgentService(llm).run_with_mcp(
                prompt=prompt, mcp_server=mcp_server, mcp_name="chat",
                stage="chat", session=session, model=MODEL_FAST, max_turns=10,
                options=MCPRunOptions(
                    on_tool_call=lambda name: tool_queue.put(name),
                    allowed_tools=allowed,
                ),
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
                yield _sse("tool_call", {"name": name, "label": TOOL_LABELS.get(name, name)})
            except Exception:
                if future.done():
                    break

        result = await future
        reply = _clean_reply(result.result_text)
        await db.append_chat_message("assistant", reply, json.dumps([], default=str))
        await _record_usage(db, result.input_tokens, result.output_tokens)
        logger.info("chat(mcp): done, %d in, %d out", result.input_tokens, result.output_tokens)
        yield _sse("text", {"content": reply, "proposals": [],
                            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens})
    except Exception as e:
        logger.exception("chat(mcp): failed")
        yield _sse("error", {"message": f"Chat failed: {e}"})
    finally:
        session.close()


async def _chat_stream_native(db, llm, messages: list[dict]) -> AsyncGenerator[str, None]:
    """Chat via native API with tool_use blocks (DirectAPIClient path)."""
    from engine.agents.service import AgentService

    tools = _make_read_tools(db)
    proposals: list[dict] = []

    def _make_handler(tool_name):
        async def handler(**kwargs):
            result, proposal = await _handle_tool(db, tool_name, kwargs)
            if proposal:
                proposals.append(proposal)
            return result
        return handler

    tool_handlers = {t["name"]: _make_handler(t["name"]) for t in tools}

    agent = AgentService(llm)
    async for event in agent.astream(
        messages=messages,
        model=MODEL_FAST,
        tools=tools,
        tool_handlers=tool_handlers,
        system=SYSTEM_PROMPT,
    ):
        if event["type"] == "tool_call":
            label = TOOL_LABELS.get(event["name"], event["name"])
            logger.info("chat: tool %s", event["name"])
            yield _sse("tool_call", {"name": event["name"], "label": label})

        elif event["type"] == "response":
            text_blocks = [b for b in event["content"] if b.type == "text"]
            reply = _clean_reply(text_blocks[-1].text if text_blocks else "")
            total_input = event["input_tokens"]
            total_output = event["output_tokens"]

            await db.append_chat_message("assistant", reply, json.dumps(proposals, default=str))
            await _record_usage(db, total_input, total_output)
            logger.info("chat: done, %d in, %d out, %d proposals", total_input, total_output, len(proposals))
            yield _sse("text", {"content": reply, "proposals": proposals,
                                "input_tokens": total_input, "output_tokens": total_output})

        elif event["type"] == "error":
            yield _sse("error", {"message": event["message"]})


@router.post("/memory/chat")
async def memory_chat(request: Request, body: ChatRequest):
    db = request.app.state.db
    llm = request.app.state.llm

    # Persist user message (last one in the list)
    if body.messages:
        last = body.messages[-1]
        if last.get("role") == "user":
            await db.append_chat_message("user", last["content"])

    return StreamingResponse(
        _chat_stream(db, llm, list(body.messages)),
        media_type="text/event-stream",
    )
