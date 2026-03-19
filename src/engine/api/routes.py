"""Ingest API (source plugins push data here) + query endpoints + engine management."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _notify_pipeline():
    """Push lightweight signal to Huey queue. No-op if Huey not available."""
    try:
        from engine.scheduler.tasks import on_new_data
        on_new_data()
    except Exception:
        pass

router = APIRouter()


async def _is_paused(db) -> bool:
    return bool(await db.get_state("pipeline_paused", 0))


# -- Unified ingest for manifest-based sources --


@router.post("/ingest/{source_name}")
async def ingest_source(request: Request, source_name: str):
    """Unified ingest endpoint for manifest-based source plugins.

    Each source posts records matching its manifest db.columns.
    Falls through to 404 if source_name is not a registered manifest source.
    """
    from engine.etl.sources.manifest_registry import insert_record
    from engine.storage.engine import get_sync_session_factory

    registry = request.app.state.manifest_registry
    if not registry.has(source_name):
        return JSONResponse({"error": f"Unknown source: {source_name}"}, status_code=404)

    db = request.app.state.db
    if await _is_paused(db):
        return {"id": None, "paused": True}

    body = await request.json()
    manifest = registry.get_manifest(source_name)
    settings = request.app.state.settings
    factory = get_sync_session_factory(settings.database_url_sync)
    session = factory()
    try:
        row_id = insert_record(session, manifest, body)
    finally:
        session.close()

    _notify_pipeline()
    return {"id": row_id}


# -- Source plugin metadata --


@router.get("/engine/sources")
async def list_sources(request: Request):
    """Return all registered manifest-based sources (for frontend dynamic rendering)."""
    registry = request.app.state.manifest_registry
    return {
        "sources": [m.raw for m in registry.all_manifests()]
    }


@router.get("/sources/{source_name}/data")
async def query_source_data(
    request: Request,
    source_name: str,
    limit: int = 50,
    offset: int = 0,
    search: str = "",
):
    """Unified query endpoint for manifest-based source data."""
    from engine.etl.sources.manifest_registry import query_records
    from engine.storage.engine import get_sync_session_factory

    registry = request.app.state.manifest_registry
    if not registry.has(source_name):
        return {"error": f"Unknown source: {source_name}"}

    manifest = registry.get_manifest(source_name)
    settings = request.app.state.settings
    factory = get_sync_session_factory(settings.database_url_sync)
    session = factory()
    try:
        records, total = query_records(session, manifest, limit=limit, offset=offset, search=search)
    finally:
        session.close()

    return {"records": records, "total": total}


# -- Source record image serving --


@router.get("/sources/{source_name}/records/{record_id}/image")
async def get_source_record_image(request: Request, source_name: str, record_id: int):
    """Serve an image from a source record's image_path column."""
    from engine.storage.engine import get_sync_session_factory

    registry = request.app.state.manifest_registry
    if not registry.has(source_name):
        return {"error": f"Unknown source: {source_name}"}

    manifest = registry.get_manifest(source_name)
    if "image_path" not in manifest.db_columns:
        return {"error": f"Source {source_name} has no image_path column"}

    settings = request.app.state.settings
    factory = get_sync_session_factory(settings.database_url_sync)
    session = factory()
    try:
        from sqlalchemy import text as sql_text
        row = session.execute(
            sql_text(f"SELECT image_path FROM {manifest.db_table} WHERE id = :id"),
            {"id": record_id},
        ).one_or_none()
    finally:
        session.close()

    if not row or not row[0]:
        return {"error": "no image"}

    image_path = row[0]
    frames_base_dir = request.app.state.settings.frames_base_dir
    file_path = Path(frames_base_dir).parent / image_path
    if not file_path.exists():
        return {"error": "file not found"}

    return FileResponse(file_path, media_type="image/webp")


# -- Memory Protocol --


@router.get("/memory/episodes/")
async def list_episodes(request: Request, limit: int = 50, offset: int = 0, search: str = ""):
    db = request.app.state.db
    episodes = await db.get_all_episodes(limit=limit, offset=offset, search=search)
    total = await db.count_episodes(search=search)
    return {"episodes": episodes, "total": total}


@router.get("/memory/playbooks/")
async def list_playbooks(request: Request, search: str = ""):
    db = request.app.state.db
    playbooks = await db.get_all_playbooks(search=search)
    return {"playbooks": playbooks}


@router.get("/memory/playbooks/{name}/history")
async def playbook_history(request: Request, name: str):
    db = request.app.state.db
    history = await db.get_playbook_history(name)
    return {"name": name, "history": history}


# -- Batch delete --


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
    # Get existing entry first
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


# -- Engine management --


@router.get("/engine/status")
async def engine_status(request: Request):
    db = request.app.state.db
    status = await db.get_status()
    return status


BUDGET_STATE_KEY = "daily_cost_cap_usd"


@router.get("/engine/budget")
async def engine_budget(request: Request):
    """Get current daily spend vs budget cap."""
    from engine.config import DAILY_COST_CAP_USD

    db = request.app.state.db
    cap = await db.get_state_float(BUDGET_STATE_KEY, DAILY_COST_CAP_USD)
    spend = await db.get_daily_spend()
    return {
        "daily_spend_usd": round(spend, 4),
        "daily_cap_usd": cap,
        "under_budget": spend < cap,
    }


class BudgetUpdate(BaseModel):
    daily_cap_usd: float


@router.put("/engine/budget")
async def set_engine_budget(request: Request, body: BudgetUpdate):
    """Set daily budget cap."""
    db = request.app.state.db
    await db.set_state_float(BUDGET_STATE_KEY, body.daily_cap_usd)
    return {"daily_cap_usd": body.daily_cap_usd}


class TryPromptRequest(BaseModel):
    prompt: str
    frame_limit: int = 30
    event_limit: int = 20
    output_path: str = ""  # save result JSON to this path if set


@router.post("/engine/try-prompt")
async def try_prompt(request: Request, body: TryPromptRequest):
    """Run episode extraction with a custom prompt on real data. For experiments."""
    import logging
    logger = logging.getLogger(__name__)
    from engine.pipeline.episode import build_context_from_dicts, extract_episodes

    db = request.app.state.db
    llm = request.app.state.llm

    frames, _ = await db.get_frames(limit=body.frame_limit)
    audio, _ = await db.get_audio_frames(limit=body.event_limit)
    os_events, _ = await db.get_os_events(limit=body.event_limit)

    if not frames:
        return {"error": "No frames in DB", "episodes": []}

    context = build_context_from_dicts(frames, audio, os_events)
    logger.info("try-prompt: %d frames, %d audio, %d events, %d context chars",
                len(frames), len(audio), len(os_events), len(context))

    try:
        episodes, resp = await extract_episodes(llm, context, prompt=body.prompt)
    except Exception as e:
        logger.exception("try-prompt: LLM call failed")
        return {"error": str(e), "episodes": []}

    result = {
        "episodes": episodes,
        "context_chars": len(context),
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
    }

    if body.output_path:
        import json
        from pathlib import Path
        Path(body.output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(body.output_path).write_text(json.dumps(result, indent=2, ensure_ascii=False))
        logger.info("try-prompt: saved to %s", body.output_path)

    return result


@router.get("/engine/usage")
async def engine_usage(request: Request, days: int = 7):
    db = request.app.state.db
    summary = await db.get_usage_summary(days=days)
    return summary


@router.get("/engine/logs")
async def pipeline_logs(request: Request, limit: int = 50, offset: int = 0, search: str = ""):
    db = request.app.state.db
    logs, total = await db.get_pipeline_logs(limit=limit, offset=offset, search=search)
    return {"logs": logs, "total": total}


@router.post("/engine/distill")
async def trigger_distill(request: Request):
    from engine.pipeline.distill import daily_distill

    llm = request.app.state.llm
    db = request.app.state.db
    count = await daily_distill(llm, db)
    return {"playbook_entries_updated": count}


@router.get("/memory/routines/")
async def list_routines(request: Request, search: str = ""):
    db = request.app.state.db
    routines = await db.get_all_routines(search)
    return {"routines": routines}


@router.post("/engine/routines")
async def trigger_routines(request: Request):
    from engine.pipeline.routines import daily_routines

    llm = request.app.state.llm
    db = request.app.state.db
    count = await daily_routines(llm, db)
    return {"routines_updated": count}


@router.post("/engine/gc")
async def trigger_gc(request: Request):
    """Manually trigger garbage collection (decay + agent audit)."""
    import asyncio
    from engine.scheduler.tasks import daily_gc_task
    await asyncio.to_thread(daily_gc_task)
    return {"status": "completed"}


def _backfill_set_processed(session, registry, value: int):
    """Set processed flag on all tables (legacy + manifest)."""
    from sqlalchemy import update, text
    from engine.storage.models import Frame as FrameModel, AudioFrame, OsEvent
    session.execute(update(FrameModel).values(processed=value))
    session.execute(update(AudioFrame).values(processed=value))
    session.execute(update(OsEvent).values(processed=value))
    if registry:
        for m in registry.all_manifests():
            if m.db_table:
                session.execute(text(f"UPDATE {m.db_table} SET processed = {value}"))
    session.commit()


def _backfill_load_all(session, registry):
    """Load all frames from legacy + manifest tables."""
    from sqlalchemy import select, text
    from engine.etl.entities import Frame
    from engine.storage.models import Frame as FrameModel, AudioFrame, OsEvent

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


@router.post("/engine/backfill")
async def backfill(request: Request):
    """Reset all frames to unprocessed and re-trigger pipeline."""
    from engine.config import Settings
    from engine.etl.filter import should_keep, detect_windows
    from engine.etl.sources.manifest_registry import get_global_registry
    from engine.scheduler.tasks import process_episode
    from engine.storage.engine import get_sync_session_factory

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
    return {
        "windows": enqueued,
        "total_frames": len(all_raw),
        "kept_frames": len(kept),
        "message": f"Enqueued {enqueued} episodes for processing",
    }


# -- Pipeline control --


@router.get("/engine/pipeline")
async def pipeline_status(request: Request):
    db = request.app.state.db
    paused = await db.get_state("pipeline_paused", 0)
    return {"paused": bool(paused)}


@router.post("/engine/pipeline/pause")
async def pipeline_pause(request: Request):
    db = request.app.state.db
    await db.set_state("pipeline_paused", 1)
    return {"paused": True}


@router.post("/engine/pipeline/resume")
async def pipeline_resume(request: Request):
    db = request.app.state.db
    await db.set_state("pipeline_paused", 0)
    return {"paused": False}


