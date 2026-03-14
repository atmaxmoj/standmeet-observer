"""
Signal collectors: poll external sources and emit Frames.

Each collector is an async function with signature:
    async def poll_xxx(db, on_frames: Queue[list[Frame]], **kwargs)

To add a new signal source, write a function following this pattern
and register it in main.py's pipeline_loop.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from engine.db import DB

logger = logging.getLogger(__name__)


@dataclass
class Frame:
    """
    A single observation from any source.

    source: where this came from ("screenpipe", "git", "shell", ...)
    app_name: the application context (for screenpipe: the focused app)
    text: the signal content (OCR text, commit message, shell command, ...)
    """

    id: int
    source: str
    text: str
    app_name: str
    window_name: str
    timestamp: str


# ---------------------------------------------------------------------------
# Screenpipe collector (reads OCR frames from Screenpipe's SQLite)
# ---------------------------------------------------------------------------


async def poll_screenpipe(
    db: DB,
    screenpipe_db_path: str,
    interval: int,
    on_frames: "asyncio.Queue[list[Frame]]",
):
    cursor_key = "screenpipe_cursor"
    logger.info("screenpipe collector started, db=%s, interval=%ds", screenpipe_db_path, interval)

    while True:
        try:
            if not Path(screenpipe_db_path).exists():
                logger.info(
                    "screenpipe DB not found at %s, waiting %ds...", screenpipe_db_path, interval * 6
                )
                await asyncio.sleep(interval * 6)
                continue

            cursor = await db.get_state(cursor_key, 0)
            logger.debug("polling screenpipe from cursor=%d", cursor)

            async with aiosqlite.connect(
                f"file:{screenpipe_db_path}?mode=ro", uri=True
            ) as sp_db:
                sp_db.row_factory = aiosqlite.Row
                async with sp_db.execute(
                    "SELECT f.id, o.text, o.app_name, o.window_name, f.timestamp "
                    "FROM frames f "
                    "JOIN ocr_text o ON o.frame_id = f.id "
                    "WHERE f.id > ? "
                    "ORDER BY f.id LIMIT 500",
                    (cursor,),
                ) as cur:
                    rows = await cur.fetchall()

            logger.debug("screenpipe query returned %d rows", len(rows))

            if rows:
                frames = [
                    Frame(
                        id=r["id"],
                        source="screenpipe",
                        text=r["text"] or "",
                        app_name=r["app_name"] or "",
                        window_name=r["window_name"] or "",
                        timestamp=r["timestamp"] or "",
                    )
                    for r in rows
                ]
                await on_frames.put(frames)
                await db.set_state(cursor_key, frames[-1].id)
                logger.debug("polled %d frames from screenpipe, new cursor=%d", len(frames), frames[-1].id)

        except Exception:
            logger.exception("Error polling Screenpipe")

        await asyncio.sleep(interval)
