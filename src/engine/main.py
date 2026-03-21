"""Observer: behavioral distillation engine.

API server (FastAPI) + Huey task queue consumer in background thread.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from engine.config import Settings
from engine.storage.db import DB

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


def _init_manifest_registry(settings: Settings):
    """Scan sources directories and register manifest-based sources."""
    from engine.etl.sources.manifest_registry import (
        ManifestRegistry, scan_sources_dir, create_table_for_manifest,
        set_global_registry,
    )
    from engine.storage.engine import get_sync_session_factory

    registry = ManifestRegistry()

    sources_dir = os.environ.get("SOURCES_DIR", "")
    if not sources_dir:
        # Default: look for sources/builtin/ relative to project root
        # Try a few common locations
        for candidate in [
            Path(__file__).resolve().parent.parent.parent / "sources" / "builtin",
            Path.cwd() / "sources" / "builtin",
        ]:
            if candidate.is_dir():
                sources_dir = str(candidate)
                break

    if sources_dir:
        manifests = scan_sources_dir(Path(sources_dir))
        if manifests:
            factory = get_sync_session_factory(settings.database_url_sync)
            session = factory()
            try:
                for m in manifests:
                    create_table_for_manifest(session, m)
                    registry.register(m)
            finally:
                session.close()
            logger.info("Registered %d manifest source(s) from %s", len(manifests), sources_dir)
    else:
        logger.debug("No SOURCES_DIR configured, skipping manifest source scan")

    set_global_registry(registry)
    return registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = DB(settings.database_url)
    await db.connect()

    app.state.db = db
    app.state.settings = settings
    app.state.manifest_registry = _init_manifest_registry(settings)

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

from engine.interfaces.api.routes import router  # noqa: E402
from engine.interfaces.api.chat import router as chat_router  # noqa: E402

app.include_router(router)
app.include_router(chat_router)
