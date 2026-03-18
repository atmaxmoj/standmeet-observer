"""Ingest API (capture/audio push data here) + query endpoints + engine management."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
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


# -- Ingest models --


class FrameIngest(BaseModel):
    timestamp: str
    app_name: str = ""
    window_name: str = ""
    text: str = ""
    display_id: int = 0
    image_hash: str = ""
    image_path: str = ""


class AudioFrameIngest(BaseModel):
    timestamp: str
    duration_seconds: float = 0.0
    text: str = ""
    language: str = ""
    source: str = "mic"
    chunk_path: str = ""


class OsEventIngest(BaseModel):
    timestamp: str
    event_type: str
    source: str = ""
    data: str = ""


# -- Ingest endpoints (capture/audio daemons POST here) --


async def _is_paused(db) -> bool:
    return bool(await db.get_state("pipeline_paused", 0))


@router.post("/ingest/frame")
async def ingest_frame(request: Request, body: FrameIngest):
    db = request.app.state.db
    if await _is_paused(db):
        return {"id": None, "paused": True}
    row_id = await db.insert_frame(
        timestamp=body.timestamp,
        app_name=body.app_name,
        window_name=body.window_name,
        text=body.text,
        display_id=body.display_id,
        image_hash=body.image_hash,
        image_path=body.image_path,
    )
    _notify_pipeline()
    return {"id": row_id}


@router.post("/ingest/audio")
async def ingest_audio(request: Request, body: AudioFrameIngest):
    db = request.app.state.db
    if await _is_paused(db):
        return {"id": None, "paused": True}
    row_id = await db.insert_audio_frame(
        timestamp=body.timestamp,
        duration_seconds=body.duration_seconds,
        text=body.text,
        language=body.language,
        source=body.source,
        chunk_path=body.chunk_path,
    )
    _notify_pipeline()
    return {"id": row_id}


@router.post("/ingest/os-event")
async def ingest_os_event(request: Request, body: OsEventIngest):
    db = request.app.state.db
    if await _is_paused(db):
        return {"id": None, "paused": True}
    row_id = await db.insert_os_event(
        timestamp=body.timestamp,
        event_type=body.event_type,
        source=body.source,
        data=body.data,
    )
    return {"id": row_id}


# -- Query endpoints --


@router.get("/capture/frames")
async def list_capture_frames(request: Request, limit: int = 50, offset: int = 0, search: str = ""):
    db = request.app.state.db
    frames, total = await db.get_frames(limit=limit, offset=offset, search=search)
    return {"frames": frames, "total": total}


@router.get("/capture/audio")
async def list_audio_frames(request: Request, limit: int = 50, offset: int = 0, search: str = ""):
    db = request.app.state.db
    audio, total = await db.get_audio_frames(limit=limit, offset=offset, search=search)
    return {"audio": audio, "total": total}


@router.get("/capture/os-events")
async def list_os_events(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    event_type: str = "",
    search: str = "",
):
    db = request.app.state.db
    events, total = await db.get_os_events(limit=limit, offset=offset, event_type=event_type, search=search)
    return {"events": events, "total": total}


# -- Frame images --


@router.get("/capture/frames/{frame_id}/image")
async def get_frame_image(request: Request, frame_id: int):
    """Serve a frame's compressed screenshot."""
    db = request.app.state.db
    image_path = await db.get_frame_image_path(frame_id)

    if not image_path:
        return {"error": "no image"}

    frames_base_dir = request.app.state.settings.frames_base_dir
    # image_path is like "frames/2026-03-14/123456_d1.webp"
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


@router.post("/engine/backfill")
async def backfill(request: Request):
    """Reset all frames to unprocessed and re-trigger pipeline.

    This reads ALL frames, runs detect_windows (ignoring recency),
    and enqueues process_episode for each window.
    """
    import sqlite3
    from engine.config import Settings
    from engine.etl.entities import Frame
    from engine.etl.filter import should_keep, detect_windows
    from engine.scheduler.tasks import process_episode

    settings = Settings()
    from sqlalchemy import create_engine
    engine = create_engine(settings.database_url_sync)
    conn = engine.raw_connection()
    if "sqlite" in settings.database_url_sync:
        conn.row_factory = sqlite3.Row

    # Reset all to unprocessed
    conn.execute("UPDATE frames SET processed = 0")
    conn.execute("UPDATE audio_frames SET processed = 0")
    conn.execute("UPDATE os_events SET processed = 0")
    conn.commit()

    # Read ALL data sources
    screen_rows = conn.execute(
        "SELECT id, timestamp, app_name, window_name, text, image_path "
        "FROM frames ORDER BY timestamp",
    ).fetchall()
    screen_frames = [
        Frame(
            id=r["id"], source="capture",
            text=r["text"] or "", app_name=r["app_name"] or "",
            window_name=r["window_name"] or "",
            timestamp=r["timestamp"] or "",
            image_path=r["image_path"] or "",
        )
        for r in screen_rows
    ]

    audio_rows = conn.execute(
        "SELECT id, timestamp, text, language "
        "FROM audio_frames ORDER BY timestamp",
    ).fetchall()
    audio_frames = [
        Frame(
            id=r["id"], source="audio",
            text=r["text"] or "", app_name="microphone",
            window_name=f"audio/{r['language'] or 'unknown'}",
            timestamp=r["timestamp"] or "",
        )
        for r in audio_rows
    ]

    os_rows = conn.execute(
        "SELECT id, timestamp, event_type, source, data "
        "FROM os_events ORDER BY timestamp",
    ).fetchall()
    os_event_frames = [
        Frame(
            id=r["id"], source="os_event",
            text=r["data"] or "", app_name=r["event_type"] or "",
            window_name=r["source"] or "",
            timestamp=r["timestamp"] or "",
        )
        for r in os_rows
    ]

    all_raw = screen_frames + audio_frames + os_event_frames
    kept = sorted(
        [f for f in all_raw if should_keep(f)],
        key=lambda f: f.timestamp,
    )

    if not kept:
        conn.execute("UPDATE frames SET processed = 1")
        conn.execute("UPDATE audio_frames SET processed = 1")
        conn.execute("UPDATE os_events SET processed = 1")
        conn.commit()
        conn.close()
        return {"windows": 0, "message": "All frames filtered as noise"}

    # Use normal idle threshold, but force-close the last group
    # (backfill treats everything as "old enough")
    windows, remainder = detect_windows(kept, window_minutes=30, idle_seconds=300)
    if remainder:
        windows.append(remainder)

    # Enqueue each window
    enqueued = 0
    for window in windows:
        screen_ids = [f.id for f in window if f.source == "capture"]
        audio_ids = [f.id for f in window if f.source == "audio"]
        os_event_ids = [f.id for f in window if f.source == "os_event"]
        process_episode(screen_ids, audio_ids, os_event_ids)
        enqueued += 1

    # Mark all as processed
    conn.execute("UPDATE frames SET processed = 1")
    conn.execute("UPDATE audio_frames SET processed = 1")
    conn.execute("UPDATE os_events SET processed = 1")
    conn.commit()
    conn.close()

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


# -- Test helper --


@router.post("/test/ingest")
async def test_ingest(request: Request):
    body = await request.json()
    db = request.app.state.db
    episode_id = await db.insert_episode(
        summary=body["summary"],
        app_names=str(body.get("app_names", "[]")),
        frame_count=0,
        started_at=body.get("started_at", ""),
        ended_at=body.get("ended_at", ""),
    )
    return {"episode_id": episode_id}
