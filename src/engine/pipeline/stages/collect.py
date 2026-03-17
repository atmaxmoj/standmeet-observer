"""Stage: collect frames from DB by IDs.

Reads raw DB rows and converts to Frame entities.
"""

import sqlite3

from engine.domain.entities.frame import Frame


def load_frames(
    conn: sqlite3.Connection,
    screen_ids: list[int],
    audio_ids: list[int],
    os_event_ids: list[int] | None = None,
) -> list[Frame]:
    """Load full frame data from DB by IDs. Returns sorted by timestamp."""
    frames: list[Frame] = []
    if screen_ids:
        placeholders = ",".join("?" * len(screen_ids))
        rows = conn.execute(
            f"SELECT id, timestamp, app_name, window_name, text, image_path "
            f"FROM frames WHERE id IN ({placeholders}) ORDER BY timestamp",
            screen_ids,
        ).fetchall()
        frames.extend(
            Frame(
                id=r["id"], source="capture",
                text=r["text"] or "", app_name=r["app_name"] or "",
                window_name=r["window_name"] or "",
                timestamp=r["timestamp"] or "",
                image_path=r["image_path"] or "",
            )
            for r in rows
        )
    if audio_ids:
        placeholders = ",".join("?" * len(audio_ids))
        rows = conn.execute(
            f"SELECT id, timestamp, text, language "
            f"FROM audio_frames WHERE id IN ({placeholders}) ORDER BY timestamp",
            audio_ids,
        ).fetchall()
        frames.extend(
            Frame(
                id=r["id"], source="audio",
                text=r["text"] or "", app_name="microphone",
                window_name=f"audio/{r['language'] or 'unknown'}",
                timestamp=r["timestamp"] or "",
            )
            for r in rows
        )
    if os_event_ids:
        placeholders = ",".join("?" * len(os_event_ids))
        rows = conn.execute(
            f"SELECT id, timestamp, event_type, source, data "
            f"FROM os_events WHERE id IN ({placeholders}) ORDER BY timestamp",
            os_event_ids,
        ).fetchall()
        frames.extend(
            Frame(
                id=r["id"], source="os_event",
                text=r["data"] or "", app_name=r["event_type"] or "",
                window_name=r["source"] or "",
                timestamp=r["timestamp"] or "",
            )
            for r in rows
        )
    frames.sort(key=lambda f: f.timestamp)
    return frames


def store_episodes(
    conn: sqlite3.Connection,
    tasks: list[dict],
    frames: list[Frame],
):
    """Write parsed episode dicts to DB."""
    import json
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

        conn.execute(
            "INSERT INTO episodes (summary, app_names, frame_count, started_at, "
            "ended_at, frame_id_min, frame_id_max, frame_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                summary,
                json.dumps(task.get("apps", [])),
                len(frames),
                task.get("started_at", frames[0].timestamp),
                task.get("ended_at", frames[-1].timestamp),
                frame_id_min,
                frame_id_max,
                frame_source,
            ),
        )
