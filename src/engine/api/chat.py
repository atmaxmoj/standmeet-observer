"""Memory chat endpoint — agent with read tools + mutation proposals."""

import json
import logging
from typing import Any

import anthropic
from fastapi import APIRouter, Request
from pydantic import BaseModel

from engine.config import MODEL_FAST

logger = logging.getLogger(__name__)

router = APIRouter()

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


class ChatRequest(BaseModel):
    messages: list[dict]


class ChatResponse(BaseModel):
    reply: str
    proposals: list[dict]
    input_tokens: int = 0
    output_tokens: int = 0


@router.post("/memory/chat")
async def memory_chat(request: Request, body: ChatRequest):
    db = request.app.state.db
    settings = request.app.state.settings

    api_key = settings.anthropic_api_key
    if not api_key:
        return ChatResponse(reply="No API key configured.", proposals=[])

    client = anthropic.AsyncAnthropic(api_key=api_key)
    tools = _make_read_tools(db)
    messages = body.messages
    proposals: list[dict] = []
    total_input = 0
    total_output = 0

    for _turn in range(8):
        response = await client.messages.create(
            model=MODEL_FAST,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        )

        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        if not tool_uses or response.stop_reason == "end_turn":
            reply = text_blocks[-1].text if text_blocks else ""
            return ChatResponse(
                reply=reply,
                proposals=proposals,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        # Execute tools
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tu in tool_uses:
            result, proposal = await _handle_tool(db, tu.name, tu.input)
            if proposal:
                proposals.append(proposal)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
            })
        messages.append({"role": "user", "content": tool_results})

    # Max turns reached
    reply = "I've reached the maximum number of steps. Please try a more specific question."
    return ChatResponse(
        reply=reply,
        proposals=proposals,
        input_tokens=total_input,
        output_tokens=total_output,
    )
