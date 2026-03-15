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
        from engine.tasks import on_new_data
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


@router.post("/ingest/frame")
async def ingest_frame(request: Request, body: FrameIngest):
    db = request.app.state.db
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
    row_id = await db.insert_os_event(
        timestamp=body.timestamp,
        event_type=body.event_type,
        source=body.source,
        data=body.data,
    )
    return {"id": row_id}


# -- Query endpoints --


@router.get("/capture/frames")
async def list_capture_frames(request: Request, limit: int = 50, offset: int = 0):
    db = request.app.state.db
    frames, total = await db.get_frames(limit=limit, offset=offset)
    return {"frames": frames, "total": total}


@router.get("/capture/audio")
async def list_audio_frames(request: Request, limit: int = 50, offset: int = 0):
    db = request.app.state.db
    audio, total = await db.get_audio_frames(limit=limit, offset=offset)
    return {"audio": audio, "total": total}


@router.get("/capture/os-events")
async def list_os_events(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    event_type: str = "",
):
    db = request.app.state.db
    events, total = await db.get_os_events(limit=limit, offset=offset, event_type=event_type)
    return {"events": events, "total": total}


# -- Frame images --


@router.get("/capture/frames/{frame_id}/image")
async def get_frame_image(request: Request, frame_id: int):
    """Serve a frame's compressed screenshot."""
    db = request.app.state.db
    async with db._conn.execute(
        "SELECT image_path FROM frames WHERE id = ?", (frame_id,)
    ) as cur:
        row = await cur.fetchone()

    if not row or not row["image_path"]:
        return {"error": "no image"}

    frames_base_dir = request.app.state.settings.frames_base_dir
    # image_path is like "frames/2026-03-14/123456_d1.webp"
    file_path = Path(frames_base_dir).parent / row["image_path"]
    if not file_path.exists():
        return {"error": "file not found"}

    return FileResponse(file_path, media_type="image/webp")


# -- Memory Protocol --


@router.get("/memory/episodes/")
async def list_episodes(request: Request, limit: int = 50, offset: int = 0):
    db = request.app.state.db
    episodes = await db.get_all_episodes(limit=limit, offset=offset)
    total = await db.count_episodes()
    return {"episodes": episodes, "total": total}


@router.get("/memory/playbooks/")
async def list_playbooks(request: Request):
    db = request.app.state.db
    playbooks = await db.get_all_playbooks()
    return {"playbooks": playbooks}


# -- Engine management --


@router.get("/engine/status")
async def engine_status(request: Request):
    db = request.app.state.db
    status = await db.get_status()
    return status


@router.get("/engine/usage")
async def engine_usage(request: Request, days: int = 7):
    db = request.app.state.db
    summary = await db.get_usage_summary(days=days)
    return summary


@router.post("/engine/distill")
async def trigger_distill(request: Request):
    from engine.pipeline.distill import weekly_distill

    llm = request.app.state.llm
    db = request.app.state.db
    count = await weekly_distill(llm, db)
    return {"playbook_entries_updated": count}


@router.post("/engine/backfill")
async def backfill(request: Request):
    """Reset all frames to unprocessed and re-trigger pipeline.

    This reads ALL frames, runs detect_windows (ignoring recency),
    and enqueues process_episode for each window.
    """
    import sqlite3
    from engine.config import Settings
    from engine.pipeline.collector import Frame
    from engine.pipeline.filter import should_keep, detect_windows
    from engine.tasks import process_episode

    settings = Settings()
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row

    # Reset all to unprocessed
    conn.execute("UPDATE frames SET processed = 0")
    conn.execute("UPDATE audio_frames SET processed = 0")
    conn.execute("UPDATE os_events SET processed = 0")
    conn.commit()

    # Read ALL frames (no limit)
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
        # Mark all as processed
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
    all_screen_ids = set()
    all_audio_ids = set()
    all_os_ids = set()
    for window in windows:
        screen_ids = [f.id for f in window if f.source == "capture"]
        audio_ids = [f.id for f in window if f.source == "audio"]
        os_event_ids = [f.id for f in window if f.source == "os_event"]
        process_episode(screen_ids, audio_ids, os_event_ids)
        all_screen_ids.update(screen_ids)
        all_audio_ids.update(audio_ids)
        all_os_ids.update(os_event_ids)
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
