"""ETL data access — frame loading, episode storage."""

import json
import sqlite3

from sqlalchemy import select, update

from engine.storage.session import get_session
from engine.storage.models import Frame as FrameModel, AudioFrame, OsEvent, Episode
from engine.etl.entities import Frame


def load_unprocessed_frames(conn: sqlite3.Connection) -> tuple[list[Frame], list[Frame], list[Frame]]:
    """Load unprocessed screen/audio/os frames. Returns (screen, audio, os)."""
    s = get_session(conn)

    screen_rows = s.execute(
        select(FrameModel).where(FrameModel.processed == 0)
        .order_by(FrameModel.timestamp).limit(500)
    ).scalars().all()
    screen = [
        Frame(id=r.id, source="capture", text=r.text or "", app_name=r.app_name or "",
              window_name=r.window_name or "", timestamp=r.timestamp or "",
              image_path=r.image_path or "")
        for r in screen_rows
    ]

    audio_rows = s.execute(
        select(AudioFrame).where(AudioFrame.processed == 0)
        .order_by(AudioFrame.timestamp).limit(100)
    ).scalars().all()
    audio = [
        Frame(id=r.id, source="audio", text=r.text or "", app_name="microphone",
              window_name=f"audio/{r.language or 'unknown'}", timestamp=r.timestamp or "")
        for r in audio_rows
    ]

    os_rows = s.execute(
        select(OsEvent).where(OsEvent.processed == 0)
        .order_by(OsEvent.timestamp).limit(200)
    ).scalars().all()
    os_frames = [
        Frame(id=r.id, source="os_event", text=r.data or "", app_name=r.event_type or "",
              window_name=r.source or "", timestamp=r.timestamp or "")
        for r in os_rows
    ]

    s.close()
    return screen, audio, os_frames


def mark_processed(
    conn: sqlite3.Connection,
    screen_ids: set[int],
    audio_ids: set[int],
    os_event_ids: set[int] | None = None,
):
    """Mark frames as processed."""
    s = get_session(conn)
    if screen_ids:
        s.execute(update(FrameModel).where(FrameModel.id.in_(screen_ids)).values(processed=1))
    if audio_ids:
        s.execute(update(AudioFrame).where(AudioFrame.id.in_(audio_ids)).values(processed=1))
    if os_event_ids:
        s.execute(update(OsEvent).where(OsEvent.id.in_(os_event_ids)).values(processed=1))
    s.commit()
    s.close()


def load_frames(
    conn: sqlite3.Connection,
    screen_ids: list[int],
    audio_ids: list[int],
    os_event_ids: list[int] | None = None,
) -> list[Frame]:
    """Load full frame data from DB by IDs. Returns sorted by timestamp."""
    s = get_session(conn)
    frames: list[Frame] = []

    if screen_ids:
        rows = s.execute(
            select(FrameModel).where(FrameModel.id.in_(screen_ids)).order_by(FrameModel.timestamp)
        ).scalars().all()
        frames.extend(
            Frame(id=r.id, source="capture", text=r.text or "", app_name=r.app_name or "",
                  window_name=r.window_name or "", timestamp=r.timestamp or "",
                  image_path=r.image_path or "")
            for r in rows
        )

    if audio_ids:
        rows = s.execute(
            select(AudioFrame).where(AudioFrame.id.in_(audio_ids)).order_by(AudioFrame.timestamp)
        ).scalars().all()
        frames.extend(
            Frame(id=r.id, source="audio", text=r.text or "", app_name="microphone",
                  window_name=f"audio/{r.language or 'unknown'}", timestamp=r.timestamp or "")
            for r in rows
        )

    if os_event_ids:
        rows = s.execute(
            select(OsEvent).where(OsEvent.id.in_(os_event_ids)).order_by(OsEvent.timestamp)
        ).scalars().all()
        frames.extend(
            Frame(id=r.id, source="os_event", text=r.data or "", app_name=r.event_type or "",
                  window_name=r.source or "", timestamp=r.timestamp or "")
            for r in rows
        )

    frames.sort(key=lambda f: f.timestamp)
    s.close()
    return frames


def store_episodes(
    conn: sqlite3.Connection,
    tasks: list[dict],
    frames: list[Frame],
):
    """Write parsed episode dicts to DB."""
    s = get_session(conn)
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

        s.add(Episode(
            summary=summary,
            app_names=json.dumps(task.get("apps", [])),
            frame_count=len(frames),
            started_at=task.get("started_at", frames[0].timestamp),
            ended_at=task.get("ended_at", frames[-1].timestamp),
            frame_id_min=frame_id_min,
            frame_id_max=frame_id_max,
            frame_source=frame_source,
        ))
    s.flush()
    s.close()
