"""Bisimulator: behavioral distillation engine."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI

from engine.config import Settings
from engine.db import DB
from engine.pipeline.collector import Frame, poll_frames, poll_audio
from engine.pipeline.episode import process_window
from engine.pipeline.filter import WindowAccumulator

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("bisimulator")


async def pipeline_loop(
    settings: Settings,
    client: anthropic.AsyncAnthropic,
    db: DB,
):
    """
    Main pipeline: collectors poll DB → noise filter → time window → Haiku.

    Data arrives via ingest API (capture/audio POST here).
    Collectors poll the same DB and push frames to the pipeline.
    """
    frame_queue: asyncio.Queue[list[Frame]] = asyncio.Queue()
    accumulator = WindowAccumulator(
        window_minutes=30,
        idle_threshold_seconds=settings.idle_threshold_seconds,
    )

    collectors = [
        asyncio.create_task(
            poll_frames(
                db=db,
                interval=settings.poll_interval_seconds,
                on_frames=frame_queue,
            )
        ),
        asyncio.create_task(
            poll_audio(
                db=db,
                interval=settings.poll_interval_seconds,
                on_frames=frame_queue,
            )
        ),
    ]

    logger.debug("pipeline loop started with %d collectors", len(collectors))

    try:
        while True:
            frames = await frame_queue.get()
            logger.debug("pipeline received %d frames from collector", len(frames))
            completed_windows = accumulator.feed(frames)

            for window_frames in completed_windows:
                logger.info(
                    "window complete: %d frames, sending to haiku",
                    len(window_frames),
                )
                await process_window(client, db, window_frames, settings.frames_base_dir)
    except asyncio.CancelledError:
        logger.info("pipeline loop cancelled, flushing remaining buffer")
        remaining = accumulator.flush()
        if remaining:
            logger.info("flushing %d remaining frames to haiku", len(remaining))
            await process_window(client, db, remaining, settings.frames_base_dir)
        for task in collectors:
            task.cancel()
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = DB(settings.db_path)
    await db.connect()

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    app.state.db = db
    app.state.anthropic = client
    app.state.settings = settings

    pipeline_task = asyncio.create_task(pipeline_loop(settings, client, db))

    logger.info(
        "Bisimulator started — polling every %ds, window=30min",
        settings.poll_interval_seconds,
    )

    yield

    pipeline_task.cancel()
    try:
        await pipeline_task
    except asyncio.CancelledError:
        pass
    await db.close()
    logger.info("Bisimulator stopped")


app = FastAPI(title="Bisimulator", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from engine.api.routes import router  # noqa: E402

app.include_router(router)
