"""Chat API endpoints — thin routing layer."""

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from engine.pipeline.chat import chat_stream, exec_delete, exec_update_playbook

router = APIRouter()


class ChatRequest(BaseModel):
    messages: list[dict]


@router.get("/memory/chat/history")
async def chat_history(request: Request):
    db = request.app.state.db
    return {"messages": await db.get_chat_messages()}


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


@router.post("/memory/chat/execute-proposal")
async def execute_proposal(request: Request, body: ProposalExecution):
    db = request.app.state.db
    if body.type == "delete" and body.table and body.ids:
        return await exec_delete(db, body.table, body.ids)
    if body.type == "update_playbook" and body.fields:
        return await exec_update_playbook(db, body.fields)
    return {"success": False, "result": {"error": f"Unknown proposal type: {body.type}"}}


class ProposalStatusUpdate(BaseModel):
    message_id: int
    proposal_index: int
    status: str


@router.post("/memory/chat/proposal-status")
async def update_proposal_status(request: Request, body: ProposalStatusUpdate):
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


@router.post("/memory/chat")
async def memory_chat(request: Request, body: ChatRequest):
    db = request.app.state.db
    settings = request.app.state.settings

    if body.messages:
        last = body.messages[-1]
        if last.get("role") == "user":
            await db.append_chat_message("user", last["content"])

    # Test agent override (set by test harness)
    agent = getattr(request.app.state, "_test_agent", None)
    return StreamingResponse(
        chat_stream(db, settings, list(body.messages), agent=agent),
        media_type="text/event-stream",
    )
