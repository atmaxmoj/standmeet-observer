"""Combined router — includes all sub-routers."""

from fastapi import APIRouter

from engine.interfaces.api.sources import router as sources_router
from engine.interfaces.api.memory import router as memory_router
from engine.interfaces.api.engine import router as engine_router

router = APIRouter()
router.include_router(sources_router)
router.include_router(memory_router)
router.include_router(engine_router)
