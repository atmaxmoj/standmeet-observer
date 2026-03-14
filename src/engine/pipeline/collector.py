"""
Signal collectors: poll engine's own DB for new frames and emit them to the pipeline.

Data flows in via ingest API (capture/audio daemons POST here),
collectors poll the DB and push frames to the pipeline queue.
"""

import asyncio
import logging
from dataclasses import dataclass

from engine.db import DB

logger = logging.getLogger(__name__)


@dataclass
class Frame:
    """
    A single observation from any source.

    source: where this came from ("capture", "audio", ...)
    app_name: the application context (for capture: the focused app)
    text: the signal content (OCR text, transcription, ...)
    image_path: relative path to compressed screenshot (empty if no image)
    """

    id: int
    source: str
    text: str
    app_name: str
    window_name: str
    timestamp: str
    image_path: str = ""


async def poll_frames(
    db: DB,
    interval: int,
    on_frames: "asyncio.Queue[list[Frame]]",
):
    """Poll engine DB for new screen capture frames."""
    cursor_key = "frames_cursor"
    logger.info("frames collector started, interval=%ds", interval)

    while True:
        try:
            cursor = await db.get_state(cursor_key, 0)

            async with db._conn.execute(
                "SELECT id, timestamp, app_name, window_name, text, image_path "
                "FROM frames WHERE id > ? ORDER BY id LIMIT 500",
                (cursor,),
            ) as cur:
                rows = await cur.fetchall()

            if rows:
                frames = [
                    Frame(
                        id=r["id"],
                        source="capture",
                        text=r["text"] or "",
                        app_name=r["app_name"] or "",
                        window_name=r["window_name"] or "",
                        timestamp=r["timestamp"] or "",
                        image_path=r["image_path"] or "",
                    )
                    for r in rows
                ]
                await on_frames.put(frames)
                await db.set_state(cursor_key, frames[-1].id)
                logger.debug("polled %d frames, new cursor=%d", len(frames), frames[-1].id)

        except Exception:
            logger.exception("error polling frames")

        await asyncio.sleep(interval)


async def poll_audio(
    db: DB,
    interval: int,
    on_frames: "asyncio.Queue[list[Frame]]",
):
    """Poll engine DB for new audio transcriptions."""
    cursor_key = "audio_cursor"
    logger.info("audio collector started, interval=%ds", interval)

    while True:
        try:
            cursor = await db.get_state(cursor_key, 0)

            async with db._conn.execute(
                "SELECT id, timestamp, text, language "
                "FROM audio_frames WHERE id > ? ORDER BY id LIMIT 100",
                (cursor,),
            ) as cur:
                rows = await cur.fetchall()

            if rows:
                frames = [
                    Frame(
                        id=r["id"],
                        source="audio",
                        text=r["text"] or "",
                        app_name="microphone",
                        window_name=f"audio/{r['language'] or 'unknown'}",
                        timestamp=r["timestamp"] or "",
                    )
                    for r in rows
                ]
                await on_frames.put(frames)
                await db.set_state(cursor_key, frames[-1].id)
                logger.debug("polled %d audio frames, new cursor=%d", len(frames), frames[-1].id)

        except Exception:
            logger.exception("error polling audio")

        await asyncio.sleep(interval)
