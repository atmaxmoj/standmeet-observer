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
from engine.pipeline.log_mutation import log_mutation
from engine.pipeline.memory_file import write_playbook, delete_playbook

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
    "propose_delete": "Proposing deletion",
    "propose_update_playbook": "Proposing playbook update",
}

SYSTEM_PROMPT = """You are the memory assistant for an observation system that captures screen frames, audio transcriptions, OS events, and distills them into episodes and behavioral playbook entries.

You can freely read any data using your tools. When the user asks you to modify data (delete, update, create), you MUST use the proposal tools instead of directly modifying. These proposals will be shown to the user for approval before execution.

Be concise and helpful. When presenting data, summarize key points rather than dumping raw JSON."""


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


async def _read_tool(db, name: str, args: dict) -> Any:
    """Execute a read-only tool. Returns result or None if not a read tool."""
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
        cursor = await db._conn.execute(
            f"SELECT id FROM {table} WHERE id = ?", (row_id,),  # noqa: S608
        )
        if await cursor.fetchone():
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
    """SSE stream generator for chat — tool-use loop with event emission."""
    tools = _make_read_tools(db)
    proposals: list[dict] = []
    total_input = 0
    total_output = 0
    logger.info("chat: starting with %d messages", len(messages))

    for _turn in range(8):
        try:
            logger.debug("chat: turn %d, calling amessages_create", _turn)
            resp = await llm.amessages_create(
                messages=messages,
                model=MODEL_FAST,
                tools=tools,
                system=SYSTEM_PROMPT,
            )
        except NotImplementedError:
            logger.warning("chat: LLM backend does not support amessages_create")
            yield _sse("error", {"message": "LLM backend does not support chat."})
            return
        except Exception:
            logger.exception("chat: amessages_create failed")
            yield _sse("error", {"message": "LLM call failed. Check engine logs."})
            return

        total_input += resp.input_tokens
        total_output += resp.output_tokens

        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        text_blocks = [b for b in resp.content if b.type == "text"]

        logger.debug("chat: turn %d got %d tool_uses, stop=%s", _turn, len(tool_uses), resp.stop_reason)

        if not tool_uses or resp.stop_reason == "end_turn":
            reply = _clean_reply(text_blocks[-1].text if text_blocks else "")
            await db.append_chat_message("assistant", reply, json.dumps(proposals, default=str))
            await _record_usage(db, total_input, total_output)
            logger.info("chat: done, %d tokens in, %d out, %d proposals", total_input, total_output, len(proposals))
            yield _sse("text", {"content": reply, "proposals": proposals,
                                "input_tokens": total_input, "output_tokens": total_output})
            return

        # Build assistant message content for conversation history
        assistant_content = []
        for b in resp.content:
            if b.type == "text":
                assistant_content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use", "id": b.tool_use_id,
                    "name": b.tool_name, "input": b.tool_input,
                })
        messages.append({"role": "assistant", "content": assistant_content})

        # Execute tool calls with SSE events
        tool_results = []
        for tu in tool_uses:
            label = TOOL_LABELS.get(tu.tool_name, tu.tool_name)
            logger.info("chat: calling tool %s", tu.tool_name)
            yield _sse("tool_call", {"name": tu.tool_name, "label": label})

            result, proposal = await _handle_tool(db, tu.tool_name, tu.tool_input or {})
            if proposal:
                proposals.append(proposal)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.tool_use_id,
                "content": json.dumps(result, default=str),
            })
        messages.append({"role": "user", "content": tool_results})

    # Max turns
    await _record_usage(db, total_input, total_output)
    yield _sse("text", {
        "content": "I've reached the maximum number of steps. Please try a more specific question.",
        "proposals": proposals,
        "input_tokens": total_input, "output_tokens": total_output,
    })


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
