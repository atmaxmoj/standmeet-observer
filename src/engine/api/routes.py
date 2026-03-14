"""Memory Protocol REST endpoints + engine management."""

import logging
from pathlib import Path

import aiosqlite
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter()


# -- Memory Protocol: episodes --


@router.get("/memory/episodes/")
async def list_episodes(request: Request, limit: int = 50, offset: int = 0):
    db = request.app.state.db
    episodes = await db.get_all_episodes(limit=limit, offset=offset)
    total = await db.count_episodes()
    return {"episodes": episodes, "total": total}


# -- Memory Protocol: playbooks --


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
    """Get token usage breakdown for the past N days."""
    db = request.app.state.db
    logger.debug("fetching usage summary for past %d days", days)
    summary = await db.get_usage_summary(days=days)
    return summary


@router.post("/engine/distill")
async def trigger_distill(request: Request):
    """Manually trigger weekly distillation (for testing)."""
    from engine.pipeline.distill import weekly_distill

    client = request.app.state.anthropic
    db = request.app.state.db
    count = await weekly_distill(client, db)
    return {"playbook_entries_updated": count}


# -- Capture frames (raw data from capture daemon) --


@router.get("/capture/frames")
async def list_capture_frames(request: Request, limit: int = 50, offset: int = 0):
    """Get recent screen capture frames from capture DB."""
    capture_db_path = request.app.state.settings.capture_db_path
    if not Path(capture_db_path).exists():
        return {"frames": [], "error": "capture DB not found"}

    async with aiosqlite.connect(
        f"file:{capture_db_path}?mode=ro", uri=True
    ) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) FROM frames") as cur:
            total = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT id, timestamp, app_name, window_name, "
            "substr(text, 1, 500) as text, display_id, image_hash "
            "FROM frames ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    return {"frames": rows, "total": total}


@router.get("/capture/audio")
async def list_audio_frames(request: Request, limit: int = 50, offset: int = 0):
    """Get recent audio transcriptions from capture DB."""
    capture_db_path = request.app.state.settings.capture_db_path
    if not Path(capture_db_path).exists():
        return {"audio": [], "error": "capture DB not found"}

    async with aiosqlite.connect(
        f"file:{capture_db_path}?mode=ro", uri=True
    ) as db:
        db.row_factory = aiosqlite.Row
        # Check if table exists
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audio_frames'"
        ) as cur:
            if not await cur.fetchone():
                return {"audio": []}

        async with db.execute("SELECT COUNT(*) FROM audio_frames") as cur:
            total = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT id, timestamp, duration_seconds, text, language, "
            "COALESCE(source, 'mic') as source "
            "FROM audio_frames ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    return {"audio": rows, "total": total}


# -- Test helper: manually ingest events --


@router.post("/test/ingest")
async def test_ingest(request: Request):
    """
    POST raw text as a test episode (bypasses Screenpipe + filter + Haiku).
    Body: {"summary": "...", "app_names": ["VSCode"], "started_at": "...", "ended_at": "..."}
    """
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
