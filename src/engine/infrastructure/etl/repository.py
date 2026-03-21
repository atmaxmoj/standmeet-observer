"""ETL data access — frame loading, episode storage."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from engine.storage.models import Frame as FrameModel, AudioFrame, OsEvent, Episode
from engine.etl.entities import Frame

if TYPE_CHECKING:
    from engine.etl.sources.manifest_registry import ManifestRegistry


def load_unprocessed_frames(session: Session) -> tuple[list[Frame], list[Frame], list[Frame]]:
    """Load unprocessed screen/audio/os frames. Returns (screen, audio, os)."""

    screen_rows = session.execute(
        select(FrameModel).where(FrameModel.processed == 0)
        .order_by(FrameModel.timestamp).limit(500)
    ).scalars().all()
    screen = [
        Frame(id=r.id, source="capture", text=r.text or "", app_name=r.app_name or "",
              window_name=r.window_name or "", timestamp=r.timestamp or "",
              image_path=r.image_path or "")
        for r in screen_rows
    ]

    audio_rows = session.execute(
        select(AudioFrame).where(AudioFrame.processed == 0)
        .order_by(AudioFrame.timestamp).limit(100)
    ).scalars().all()
    audio = [
        Frame(id=r.id, source="audio", text=r.text or "", app_name="microphone",
              window_name=f"audio/{r.language or 'unknown'}", timestamp=r.timestamp or "")
        for r in audio_rows
    ]

    os_rows = session.execute(
        select(OsEvent).where(OsEvent.processed == 0)
        .order_by(OsEvent.timestamp).limit(200)
    ).scalars().all()
    os_frames = [
        Frame(id=r.id, source="os_event", text=r.data or "", app_name=r.event_type or "",
              window_name=r.source or "", timestamp=r.timestamp or "")
        for r in os_rows
    ]

    return screen, audio, os_frames


def mark_processed(
    session: Session,
    screen_ids: set[int],
    audio_ids: set[int],
    os_event_ids: set[int] | None = None,
):
    """Mark frames as processed."""
    if screen_ids:
        session.execute(update(FrameModel).where(FrameModel.id.in_(screen_ids)).values(processed=1))
    if audio_ids:
        session.execute(update(AudioFrame).where(AudioFrame.id.in_(audio_ids)).values(processed=1))
    if os_event_ids:
        session.execute(update(OsEvent).where(OsEvent.id.in_(os_event_ids)).values(processed=1))
    session.commit()


def load_frames(
    session: Session,
    screen_ids: list[int],
    audio_ids: list[int],
    os_event_ids: list[int] | None = None,
) -> list[Frame]:
    """Load full frame data from DB by IDs. Returns sorted by timestamp."""
    frames: list[Frame] = []

    if screen_ids:
        rows = session.execute(
            select(FrameModel).where(FrameModel.id.in_(screen_ids)).order_by(FrameModel.timestamp)
        ).scalars().all()
        frames.extend(
            Frame(id=r.id, source="capture", text=r.text or "", app_name=r.app_name or "",
                  window_name=r.window_name or "", timestamp=r.timestamp or "",
                  image_path=r.image_path or "")
            for r in rows
        )

    if audio_ids:
        rows = session.execute(
            select(AudioFrame).where(AudioFrame.id.in_(audio_ids)).order_by(AudioFrame.timestamp)
        ).scalars().all()
        frames.extend(
            Frame(id=r.id, source="audio", text=r.text or "", app_name="microphone",
                  window_name=f"audio/{r.language or 'unknown'}", timestamp=r.timestamp or "")
            for r in rows
        )

    if os_event_ids:
        rows = session.execute(
            select(OsEvent).where(OsEvent.id.in_(os_event_ids)).order_by(OsEvent.timestamp)
        ).scalars().all()
        frames.extend(
            Frame(id=r.id, source="os_event", text=r.data or "", app_name=r.event_type or "",
                  window_name=r.source or "", timestamp=r.timestamp or "")
            for r in rows
        )

    frames.sort(key=lambda f: f.timestamp)
    return frames


def load_unprocessed_source_frames(
    session: Session,
    registry: "ManifestRegistry",
) -> dict[str, list[Frame]]:
    """Load unprocessed frames from all manifest-based source tables.

    Returns dict mapping source_name -> list of Frame entities.
    """
    from sqlalchemy import text
    result = {}
    for manifest in registry.all_manifests():
        if not manifest.db_table:
            continue
        source = registry.get_source(manifest.name)
        cols = ", ".join(source.db_columns())
        sql = f"SELECT {cols} FROM {manifest.db_table} WHERE processed = 0 ORDER BY timestamp LIMIT 500"
        rows = session.execute(text(sql)).mappings().all()
        frames = [source.to_frame(dict(r)) for r in rows]
        if frames:
            result[manifest.name] = frames
    return result


def mark_source_processed(
    session: Session,
    registry: "ManifestRegistry",
    source_ids: dict[str, set[int]],
):
    """Mark frames as processed in manifest-based source tables."""
    from sqlalchemy import text
    for source_name, ids in source_ids.items():
        if not ids:
            continue
        manifest = registry.get_manifest(source_name)
        placeholders = ",".join(str(i) for i in ids)
        session.execute(text(f"UPDATE {manifest.db_table} SET processed = 1 WHERE id IN ({placeholders})"))
    session.commit()


def load_source_frames(
    session: Session,
    registry: "ManifestRegistry",
    source_ids: dict[str, list[int]],
) -> list[Frame]:
    """Load frames from manifest-based source tables by IDs."""
    from sqlalchemy import text
    frames = []
    for source_name, ids in source_ids.items():
        if not ids:
            continue
        manifest = registry.get_manifest(source_name)
        source = registry.get_source(source_name)
        placeholders = ",".join(str(i) for i in ids)
        cols = ", ".join(source.db_columns())
        sql = f"SELECT {cols} FROM {manifest.db_table} WHERE id IN ({placeholders}) ORDER BY timestamp"
        rows = session.execute(text(sql)).mappings().all()
        frames.extend(source.to_frame(dict(r)) for r in rows)
    frames.sort(key=lambda f: f.timestamp)
    return frames


def store_episodes(
    session: Session,
    tasks: list[dict],
    frames: list[Frame],
):
    """Write parsed episode dicts to DB."""
    frame_id_min = min(f.id for f in frames)
    frame_id_max = max(f.id for f in frames)
    frame_source = ",".join(sorted({f.source for f in frames}))

    for task in tasks:
        summary = json.dumps({
            "summary": task.get("summary", ""),
            "method": task.get("method", ""),
            "turning_points": task.get("turning_points", []),
            "avoidance": task.get("avoidance", []),
            "under_pressure": task.get("under_pressure", False),
        }, ensure_ascii=False)

        session.add(Episode(
            summary=summary,
            app_names=json.dumps(task.get("apps", [])),
            frame_count=len(frames),
            started_at=task.get("started_at", frames[0].timestamp),
            ended_at=task.get("ended_at", frames[-1].timestamp),
            frame_id_min=frame_id_min,
            frame_id_max=frame_id_max,
            frame_source=frame_source,
        ))
    session.flush()
