"""Huey task queue for behavioral distillation pipeline.

Queue-native design:
- Ingest endpoints push lightweight signals to queue (no data, just "check now")
- on_new_data: reads unprocessed frames from DB, detects windows, enqueues episodes
- process_episode: receives frame IDs, reads full data from DB, calls LLM
- DB owns all data + progress tracking (processed column)
"""

import json
import logging
import sqlite3
from pathlib import Path

from huey import SqliteHuey, crontab

from engine.config import Settings, MODEL_TASK, MODEL_WEEKLY
from engine.llm import create_client
from engine.pipeline.collector import Frame
from engine.pipeline.episode import EPISODE_PROMPT
from engine.pipeline.distill import DISTILL_PROMPT
from engine.pipeline.filter import should_keep, detect_windows

logger = logging.getLogger(__name__)

settings = Settings()

huey = SqliteHuey(
    filename=str(Path(settings.db_path).parent / "huey.db"),
)

_llm = create_client(
    api_key=settings.anthropic_api_key,
    auth_token=settings.claude_code_oauth_token,
    openai_api_key=settings.openai_api_key,
    openai_base_url=settings.openai_base_url,
)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# -- Triggered by ingest: check if pending frames form complete windows --


@huey.task()
@huey.lock_task("pipeline-check")
def on_new_data():
    """Check unprocessed frames for complete windows. Deduplicated by lock."""
    conn = _get_conn()
    try:
        # Read all unprocessed frames
        screen_rows = conn.execute(
            "SELECT id, timestamp, app_name, window_name, text, image_path "
            "FROM frames WHERE processed = 0 ORDER BY timestamp LIMIT 500",
        ).fetchall()
        screen_frames = [
            Frame(
                id=r["id"], source="capture",
                text=r["text"] or "", app_name=r["app_name"] or "",
                window_name=r["window_name"] or "",
                timestamp=r["timestamp"] or "",
                image_path=r["image_path"] or "",
            )
            for r in screen_rows
        ]

        audio_rows = conn.execute(
            "SELECT id, timestamp, text, language "
            "FROM audio_frames WHERE processed = 0 ORDER BY timestamp LIMIT 100",
        ).fetchall()
        audio_frames = [
            Frame(
                id=r["id"], source="audio",
                text=r["text"] or "", app_name="microphone",
                window_name=f"audio/{r['language'] or 'unknown'}",
                timestamp=r["timestamp"] or "",
            )
            for r in audio_rows
        ]

        if not screen_frames and not audio_frames:
            return

        all_raw = screen_frames + audio_frames
        all_screen_ids = {f.id for f in screen_frames}
        all_audio_ids = {f.id for f in audio_frames}

        # Filter noise + sort
        kept = sorted(
            [f for f in all_raw if should_keep(f)],
            key=lambda f: f.timestamp,
        )

        if not kept:
            # All noise — mark everything processed
            _mark_processed(conn, all_screen_ids, all_audio_ids)
            return

        # Detect windows
        windows, remainder = detect_windows(
            kept,
            window_minutes=30,
            idle_seconds=settings.idle_threshold_seconds,
        )

        if not windows:
            logger.debug(
                "on_new_data: %d pending frames, no complete windows yet",
                len(all_raw),
            )
            return

        logger.info(
            "on_new_data: %d windows from %d frames (%d remainder)",
            len(windows), len(all_raw), len(remainder),
        )

        # Enqueue episode processing — only IDs, lightweight
        for window in windows:
            screen_ids = [f.id for f in window if f.source == "capture"]
            audio_ids = [f.id for f in window if f.source == "audio"]
            process_episode(screen_ids, audio_ids)

        # Mark everything EXCEPT remainder as processed
        remainder_ids = {f.id for f in remainder}
        _mark_processed(
            conn,
            all_screen_ids - remainder_ids,
            all_audio_ids - remainder_ids,
        )

    except Exception:
        logger.exception("on_new_data failed")
    finally:
        conn.close()


def _mark_processed(
    conn: sqlite3.Connection,
    screen_ids: set[int],
    audio_ids: set[int],
):
    """Mark frames as processed in DB."""
    if screen_ids:
        placeholders = ",".join("?" * len(screen_ids))
        conn.execute(
            f"UPDATE frames SET processed = 1 WHERE id IN ({placeholders})",
            list(screen_ids),
        )
    if audio_ids:
        placeholders = ",".join("?" * len(audio_ids))
        conn.execute(
            f"UPDATE audio_frames SET processed = 1 WHERE id IN ({placeholders})",
            list(audio_ids),
        )
    conn.commit()


# -- Process a window: read full data from DB by IDs, call Haiku --


def _load_frames(
    conn: sqlite3.Connection,
    screen_ids: list[int],
    audio_ids: list[int],
) -> list[Frame]:
    """Load full frame data from DB by IDs."""
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
    frames.sort(key=lambda f: f.timestamp)
    return frames


def _build_prompt(frames: list[Frame]) -> str:
    """Build text prompt from frames for Claude."""
    context_lines = []
    for f in frames:
        text = f.text[:300].replace("\n", " ")
        source_tag = f"[{f.source}]" if f.source != "screenpipe" else ""
        context_lines.append(
            f"[{f.timestamp}] {f.app_name}/{f.window_name}{source_tag}: {text}"
        )
    return EPISODE_PROMPT.format(context="\n".join(context_lines))


def _store_episodes(
    conn: sqlite3.Connection,
    tasks: list[dict],
    frames: list[Frame],
):
    """Write parsed Haiku tasks to episodes table."""
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


@huey.task(retries=2, retry_delay=30)
def process_episode(screen_ids: list[int], audio_ids: list[int]):
    """Read frame data from DB, call Claude Agent SDK, store episodes."""
    if not screen_ids and not audio_ids:
        return

    conn = _get_conn()
    try:
        frames = _load_frames(conn, screen_ids, audio_ids)
        if not frames:
            return

        logger.info(
            "process_episode: %d frames [%s -> %s]",
            len(frames), frames[0].timestamp, frames[-1].timestamp,
        )

        prompt = _build_prompt(frames)
        resp = _llm.complete(prompt, MODEL_TASK)

        # Parse JSON response
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        tasks = json.loads(text)
        if not isinstance(tasks, list):
            tasks = [tasks]

        _store_episodes(conn, tasks, frames)

        # Record usage
        cost = resp.cost_usd or 0
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (MODEL_TASK, "episode", resp.input_tokens, resp.output_tokens, cost),
        )
        conn.commit()

        logger.info(
            "process_episode: created %d episodes, cost=$%.4f",
            len(tasks), cost,
        )

    except Exception:
        logger.exception("process_episode failed")
    finally:
        conn.close()


# -- Weekly playbook distillation --


@huey.periodic_task(crontab(day_of_week="0", hour="3", minute="0"))
def weekly_distill_task():
    """Weekly playbook distillation with Opus. Runs Sunday 3am."""
    conn = _get_conn()
    try:
        episodes = conn.execute(
            "SELECT * FROM episodes WHERE created_at >= datetime('now', '-7 days') "
            "ORDER BY created_at",
        ).fetchall()

        if not episodes:
            logger.info("weekly distill: no episodes, skipping")
            return

        existing = conn.execute(
            "SELECT * FROM playbook_entries ORDER BY confidence DESC",
        ).fetchall()

        episodes_text = "\n\n".join(
            f"Episode #{e['id']} ({e['started_at']} to {e['ended_at']}):\n{e['summary']}"
            for e in episodes
        )

        playbooks_text = (
            "\n\n".join(
                f"- **{p['name']}** (confidence: {p['confidence']}, "
                f"maturity: {p['maturity'] or 'nascent'})\n"
                f"  Context: {p['context']}\n"
                f"  Action: {p['action']}\n"
                f"  Evidence: {p['evidence']}"
                for p in existing
            )
            if existing
            else "(none yet — this is the first distillation)"
        )

        prompt = DISTILL_PROMPT.format(
            playbooks=playbooks_text, episodes=episodes_text,
        )
        resp = _llm.complete(prompt, MODEL_WEEKLY)

        cost = resp.cost_usd or 0
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (MODEL_WEEKLY, "distill", resp.input_tokens, resp.output_tokens, cost),
        )

        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        entries = json.loads(text)
        if not isinstance(entries, list):
            entries = [entries]

        count = 0
        for entry in entries:
            rich_action = json.dumps({
                "intuition": entry.get("intuition", ""),
                "action": entry.get("action", ""),
                "why": entry.get("why", ""),
                "counterexample": entry.get("counterexample"),
            }, ensure_ascii=False)

            conn.execute(
                "INSERT INTO playbook_entries (name, context, action, confidence, "
                "maturity, evidence, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(name) DO UPDATE SET "
                "context=excluded.context, action=excluded.action, "
                "confidence=excluded.confidence, maturity=excluded.maturity, "
                "evidence=excluded.evidence, updated_at=datetime('now')",
                (
                    entry["name"],
                    entry.get("context", ""),
                    rich_action,
                    entry.get("confidence", 0.5),
                    entry.get("maturity", "nascent"),
                    json.dumps(entry.get("evidence", [])),
                ),
            )
            count += 1

        conn.commit()
        logger.info(
            "weekly distill: %d entries from %d episodes, cost=$%.4f",
            count, len(episodes), cost,
        )

    except Exception:
        logger.exception("weekly distill failed")
    finally:
        conn.close()
