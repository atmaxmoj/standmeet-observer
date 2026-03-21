"""Source plugin endpoints — ingest, query, images."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _notify_pipeline():
    try:
        from engine.infrastructure.scheduler.tasks import on_new_data
        on_new_data()
    except Exception:
        pass


@router.post("/ingest/{source_name}")
async def ingest_source(request: Request, source_name: str):
    from engine.infrastructure.etl.sources.manifest_registry import insert_record
    from engine.infrastructure.persistence.engine import get_sync_session_factory

    registry = request.app.state.manifest_registry
    if not registry.has(source_name):
        return JSONResponse({"error": f"Unknown source: {source_name}"}, status_code=404)

    db = request.app.state.db
    if bool(await db.get_state("pipeline_paused", 0)):
        return {"id": None, "paused": True}

    body = await request.json()
    manifest = registry.get_manifest(source_name)
    settings = request.app.state.settings
    factory = get_sync_session_factory(settings.database_url_sync)
    session = factory()
    try:
        row_id = insert_record(session, manifest, body)
    finally:
        session.close()

    _notify_pipeline()
    return {"id": row_id}


@router.get("/engine/sources")
async def list_sources(request: Request):
    registry = request.app.state.manifest_registry
    return {"sources": [m.raw for m in registry.all_manifests()]}


@router.get("/sources/{source_name}/data")
async def query_source_data(request: Request, source_name: str,
                            limit: int = 50, offset: int = 0, search: str = ""):
    from engine.infrastructure.etl.sources.manifest_registry import query_records
    from engine.infrastructure.persistence.engine import get_sync_session_factory

    registry = request.app.state.manifest_registry
    if not registry.has(source_name):
        return {"error": f"Unknown source: {source_name}"}

    manifest = registry.get_manifest(source_name)
    settings = request.app.state.settings
    factory = get_sync_session_factory(settings.database_url_sync)
    session = factory()
    try:
        records, total = query_records(session, manifest, limit=limit, offset=offset, search=search)
    finally:
        session.close()

    return {"records": records, "total": total}


@router.get("/sources/{source_name}/records/{record_id}/image")
async def get_source_record_image(request: Request, source_name: str, record_id: int):
    from engine.infrastructure.persistence.engine import get_sync_session_factory

    registry = request.app.state.manifest_registry
    if not registry.has(source_name):
        return {"error": f"Unknown source: {source_name}"}

    manifest = registry.get_manifest(source_name)
    if "image_path" not in manifest.db_columns:
        return {"error": f"Source {source_name} has no image_path column"}

    settings = request.app.state.settings
    factory = get_sync_session_factory(settings.database_url_sync)
    session = factory()
    try:
        from sqlalchemy import text as sql_text
        row = session.execute(
            sql_text(f"SELECT image_path FROM {manifest.db_table} WHERE id = :id"),
            {"id": record_id},
        ).one_or_none()
    finally:
        session.close()

    if not row or not row[0]:
        return {"error": "no image"}

    file_path = Path(request.app.state.settings.frames_base_dir).parent / row[0]
    if not file_path.exists():
        return {"error": "file not found"}

    return FileResponse(file_path, media_type="image/webp")
