"""Engine management endpoints — status, budget, pipeline, distill, routines, gc, backfill."""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

BUDGET_STATE_KEY = "daily_cost_cap_usd"


@router.get("/engine/status")
async def engine_status(request: Request):
    return await request.app.state.db.get_status()


@router.get("/engine/budget")
async def engine_budget(request: Request):
    from engine.config import DAILY_COST_CAP_USD
    db = request.app.state.db
    cap = await db.get_state_float(BUDGET_STATE_KEY, DAILY_COST_CAP_USD)
    spend = await db.get_daily_spend()
    return {"daily_spend_usd": round(spend, 4), "daily_cap_usd": cap, "under_budget": spend < cap}


class BudgetUpdate(BaseModel):
    daily_cap_usd: float


@router.put("/engine/budget")
async def set_engine_budget(request: Request, body: BudgetUpdate):
    await request.app.state.db.set_state_float(BUDGET_STATE_KEY, body.daily_cap_usd)
    return {"daily_cap_usd": body.daily_cap_usd}


class TryPromptRequest(BaseModel):
    prompt: str
    frame_limit: int = 30
    event_limit: int = 20
    output_path: str = ""


@router.post("/engine/try-prompt")
async def try_prompt(request: Request, body: TryPromptRequest):
    from engine.infrastructure.pipeline.stages.extract import build_context_from_dicts, extract_episodes

    db = request.app.state.db
    settings = request.app.state.settings
    frames, _ = await db.get_frames(limit=body.frame_limit)
    audio, _ = await db.get_audio_frames(limit=body.event_limit)
    os_events, _ = await db.get_os_events(limit=body.event_limit)

    if not frames:
        return {"error": "No frames in DB", "episodes": []}

    context = build_context_from_dicts(frames, audio, os_events)

    try:
        from engine.infrastructure.agent.service import AgentService
        episodes, resp = await extract_episodes(AgentService(settings), context, prompt=body.prompt)
    except Exception as e:
        logger.exception("try-prompt: LLM call failed")
        return {"error": str(e), "episodes": []}

    result = {
        "episodes": episodes, "context_chars": len(context),
        "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
    }
    if body.output_path:
        import json
        from pathlib import Path
        Path(body.output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(body.output_path).write_text(json.dumps(result, indent=2, ensure_ascii=False))

    return result


@router.get("/engine/usage")
async def engine_usage(request: Request, days: int = 7):
    return await request.app.state.db.get_usage_summary(days=days)


@router.get("/engine/logs")
async def pipeline_logs(request: Request, limit: int = 50, offset: int = 0, search: str = ""):
    logs, total = await request.app.state.db.get_pipeline_logs(limit=limit, offset=offset, search=search)
    return {"logs": logs, "total": total}


@router.post("/engine/distill")
async def trigger_distill(request: Request):
    from engine.application.distill_playbooks import distill_playbooks
    count = await distill_playbooks(request.app.state.settings, request.app.state.db)
    return {"playbook_entries_updated": count}


@router.post("/engine/routines")
async def trigger_routines(request: Request):
    from engine.application.compose_routines import compose_routines
    count = await compose_routines(request.app.state.settings, request.app.state.db)
    return {"routines_updated": count}


@router.post("/engine/gc")
async def trigger_gc(request: Request):
    import asyncio
    from engine.application.gc import run_gc
    from engine.infrastructure.persistence.engine import get_sync_session_factory

    settings = request.app.state.settings
    session = get_sync_session_factory(settings.database_url_sync)()
    try:
        result = await asyncio.to_thread(run_gc, settings, session)
    finally:
        session.close()
    return result


@router.post("/engine/backfill")
async def backfill(request: Request):
    from engine.config import Settings
    from engine.domain.observation.filter import should_keep, detect_windows
    from engine.infrastructure.etl.sources.manifest_registry import get_global_registry
    from engine.scheduler.tasks import process_episode
    from engine.infrastructure.persistence.engine import get_sync_session_factory

    settings = Settings()
    factory = get_sync_session_factory(settings.database_url_sync)
    session = factory()
    registry = get_global_registry()

    _backfill_set_processed(session, registry, 0)
    all_raw = _backfill_load_all(session, registry)

    kept = sorted([f for f in all_raw if should_keep(f)], key=lambda f: f.timestamp)
    if not kept:
        _backfill_set_processed(session, registry, 1)
        session.close()
        return {"windows": 0, "message": "All frames filtered as noise"}

    windows, remainder = detect_windows(kept, window_minutes=30, idle_seconds=300)
    if remainder:
        windows.append(remainder)

    known_sources = {"capture", "audio", "os_event"}
    enqueued = 0
    for window in windows:
        screen_ids = [f.id for f in window if f.source == "capture"]
        audio_ids = [f.id for f in window if f.source == "audio"]
        os_event_ids = [f.id for f in window if f.source == "os_event"]
        window_source_ids: dict[str, list[int]] = {}
        for f in window:
            if f.source not in known_sources:
                window_source_ids.setdefault(f.source, []).append(f.id)
        process_episode(screen_ids, audio_ids, os_event_ids, window_source_ids or None)
        enqueued += 1

    _backfill_set_processed(session, registry, 1)
    session.close()

    logger.info("backfill: enqueued %d windows from %d frames", enqueued, len(all_raw))
    return {"windows": enqueued, "total_frames": len(all_raw), "kept_frames": len(kept)}


@router.get("/engine/pipeline")
async def pipeline_status(request: Request):
    return {"paused": bool(await request.app.state.db.get_state("pipeline_paused", 0))}


@router.post("/engine/pipeline/pause")
async def pipeline_pause(request: Request):
    await request.app.state.db.set_state("pipeline_paused", 1)
    return {"paused": True}


@router.post("/engine/pipeline/resume")
async def pipeline_resume(request: Request):
    await request.app.state.db.set_state("pipeline_paused", 0)
    return {"paused": False}


def _backfill_set_processed(session, registry, value: int):
    from sqlalchemy import update, text
    from engine.infrastructure.persistence.models import Frame as FrameModel, AudioFrame, OsEvent
    session.execute(update(FrameModel).values(processed=value))
    session.execute(update(AudioFrame).values(processed=value))
    session.execute(update(OsEvent).values(processed=value))
    if registry:
        for m in registry.all_manifests():
            if m.db_table:
                session.execute(text(f"UPDATE {m.db_table} SET processed = {value}"))
    session.commit()


def _backfill_load_all(session, registry):
    from sqlalchemy import select, text
    from engine.domain.observation.entity import Frame
    from engine.infrastructure.persistence.models import Frame as FrameModel, AudioFrame, OsEvent

    all_raw = []
    for r in session.execute(select(FrameModel).order_by(FrameModel.timestamp)).scalars():
        all_raw.append(Frame(id=r.id, source="capture", text=r.text or "",
                             app_name=r.app_name or "", window_name=r.window_name or "",
                             timestamp=r.timestamp or "", image_path=r.image_path or ""))
    for r in session.execute(select(AudioFrame).order_by(AudioFrame.timestamp)).scalars():
        all_raw.append(Frame(id=r.id, source="audio", text=r.text or "",
                             app_name="microphone", window_name=f"audio/{r.language or 'unknown'}",
                             timestamp=r.timestamp or ""))
    for r in session.execute(select(OsEvent).order_by(OsEvent.timestamp)).scalars():
        all_raw.append(Frame(id=r.id, source="os_event", text=r.data or "",
                             app_name=r.event_type or "", window_name=r.source or "",
                             timestamp=r.timestamp or ""))
    if registry:
        for manifest in registry.all_manifests():
            if not manifest.db_table:
                continue
            source = registry.get_source(manifest.name)
            cols = ", ".join(source.db_columns())
            rows = session.execute(text(f"SELECT {cols} FROM {manifest.db_table} ORDER BY timestamp")).mappings()
            all_raw.extend(source.to_frame(dict(r)) for r in rows)
    return all_raw
