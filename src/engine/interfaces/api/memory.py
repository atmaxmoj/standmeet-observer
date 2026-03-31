"""Memory endpoints — episodes, playbooks, routines."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


@router.get("/memory/episodes/")
async def list_episodes(request: Request, limit: int = 50, offset: int = 0, search: str = ""):
    db = request.app.state.db
    episodes = await db.get_all_episodes(limit=limit, offset=offset, search=search)
    total = await db.count_episodes(search=search)
    return {"episodes": episodes, "total": total}


@router.get("/memory/playbooks/")
async def list_playbooks(request: Request, search: str = ""):
    db = request.app.state.db
    return {"playbooks": await db.get_all_playbooks(search=search)}


@router.get("/memory/playbooks/{name}/history")
async def playbook_history(request: Request, name: str):
    db = request.app.state.db
    return {"name": name, "history": await db.get_playbook_history(name)}


@router.get("/memory/routines/")
async def list_routines(request: Request, search: str = ""):
    db = request.app.state.db
    return {"routines": await db.get_all_routines(search)}


@router.get("/memory/insights/")
async def list_insights(request: Request, limit: int = 50, offset: int = 0):
    db = request.app.state.db
    return {"insights": await db.get_insights(limit, offset), "total": await db.count_insights()}


@router.get("/memory/da-goals/")
async def list_da_goals(request: Request):
    db = request.app.state.db
    return {"goals": await db.get_da_goals()}


class BatchDelete(BaseModel):
    table: str
    ids: list[int]


@router.post("/batch/delete")
async def batch_delete(request: Request, body: BatchDelete):
    db = request.app.state.db
    try:
        deleted = await db.delete_rows(body.table, body.ids)
    except ValueError as e:
        return {"error": str(e), "deleted": 0}
    return {"deleted": deleted}


class PlaybookUpdate(BaseModel):
    name: str
    context: str | None = None
    action: str | None = None
    confidence: float | None = None
    maturity: str | None = None


@router.post("/batch/update-playbook")
async def update_playbook(request: Request, body: PlaybookUpdate):
    db = request.app.state.db
    playbooks = await db.get_all_playbooks()
    existing = next((p for p in playbooks if p["name"] == body.name), None)
    if not existing:
        return {"error": f"Playbook entry '{body.name}' not found", "updated": False}
    await db.upsert_playbook(
        name=body.name,
        context=body.context if body.context is not None else existing["context"],
        action=body.action if body.action is not None else existing["action"],
        confidence=body.confidence if body.confidence is not None else existing["confidence"],
        evidence=existing["evidence"],
        maturity=body.maturity if body.maturity is not None else existing["maturity"],
    )
    return {"updated": True}
