"""Ingest API (capture/audio push data here) + query endpoints + engine management."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

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

    client = request.app.state.anthropic
    db = request.app.state.db
    count = await weekly_distill(client, db)
    return {"playbook_entries_updated": count}


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
