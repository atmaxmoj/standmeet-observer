"""Observer: behavioral distillation engine.

API server (FastAPI) + Huey task queue consumer in background thread.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from engine.config import Settings
from engine.storage.db import DB
from engine.llm import create_client

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("observer")


def _start_huey_consumer():
    """Start Huey consumer in a daemon thread (no signal handler conflicts)."""
    from huey.consumer import Consumer
    from engine.scheduler.tasks import huey

    class EmbeddedConsumer(Consumer):
        def _set_signal_handlers(self):
            pass  # Skip — uvicorn handles signals

    consumer = EmbeddedConsumer(huey, workers=2, periodic=True)
    thread = threading.Thread(target=consumer.run, daemon=True, name="huey")
    thread.start()
    logger.info("Huey consumer started in background thread")
    return consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = DB(settings.database_url)
    await db.connect()

    llm = create_client(
        api_key=settings.anthropic_api_key,
        auth_token=settings.claude_code_oauth_token,
        openai_api_key=settings.openai_api_key,
        openai_base_url=settings.openai_base_url,
    )

    app.state.db = db
    app.state.llm = llm
    app.state.settings = settings

    _start_huey_consumer()

    logger.info("Observer started — Huey handles pipeline scheduling")

    yield

    # Huey consumer thread is daemon, exits with process
    await db.close()
    logger.info("Observer stopped")


app = FastAPI(title="Observer", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from engine.api.routes import router  # noqa: E402
from engine.api.chat import router as chat_router  # noqa: E402

app.include_router(router)
app.include_router(chat_router)
