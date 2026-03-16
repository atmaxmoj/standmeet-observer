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

from engine.config import Settings, MODEL_FAST, MODEL_DEEP, DAILY_COST_CAP_USD
from engine.llm import create_client
from engine.pipeline.collector import Frame
from engine.pipeline.episode import EPISODE_PROMPT
from engine.pipeline.distill import DISTILL_PROMPT
from engine.pipeline.routines import ROUTINE_PROMPT
from engine.pipeline.filter import should_keep, detect_windows
from engine.pipeline.validate import validate_episodes, validate_playbooks, with_retry
from engine.pipeline.budget import check_daily_budget

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

        os_rows = conn.execute(
            "SELECT id, timestamp, event_type, source, data "
            "FROM os_events WHERE processed = 0 ORDER BY timestamp LIMIT 200",
        ).fetchall()
        os_frames = [
            Frame(
                id=r["id"], source="os_event",
                text=r["data"] or "", app_name=r["event_type"] or "",
                window_name=r["source"] or "",
                timestamp=r["timestamp"] or "",
            )
            for r in os_rows
        ]

        if not screen_frames and not audio_frames and not os_frames:
            return

        all_raw = screen_frames + audio_frames + os_frames
        all_screen_ids = {f.id for f in screen_frames}
        all_audio_ids = {f.id for f in audio_frames}
        all_os_ids = {f.id for f in os_frames}

        # Filter noise + sort
        kept = sorted(
            [f for f in all_raw if should_keep(f)],
            key=lambda f: f.timestamp,
        )

        if not kept:
            _mark_processed(conn, all_screen_ids, all_audio_ids, all_os_ids)
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

        # Enqueue episode processing
        for window in windows:
            screen_ids = [f.id for f in window if f.source == "capture"]
            audio_ids = [f.id for f in window if f.source == "audio"]
            os_event_ids = [f.id for f in window if f.source == "os_event"]
            process_episode(screen_ids, audio_ids, os_event_ids)

        # Mark everything EXCEPT remainder as processed
        remainder_ids = {f.id for f in remainder}
        _mark_processed(
            conn,
            all_screen_ids - remainder_ids,
            all_audio_ids - remainder_ids,
            all_os_ids - remainder_ids,
        )

    except Exception:
        logger.exception("on_new_data failed")
    finally:
        conn.close()


def _mark_processed(
    conn: sqlite3.Connection,
    screen_ids: set[int],
    audio_ids: set[int],
    os_event_ids: set[int] | None = None,
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
    if os_event_ids:
        placeholders = ",".join("?" * len(os_event_ids))
        conn.execute(
            f"UPDATE os_events SET processed = 1 WHERE id IN ({placeholders})",
            list(os_event_ids),
        )
    conn.commit()


# -- Process a window: read full data from DB by IDs, call Haiku --


def _load_frames(
    conn: sqlite3.Connection,
    screen_ids: list[int],
    audio_ids: list[int],
    os_event_ids: list[int] | None = None,
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
def process_episode(
    screen_ids: list[int],
    audio_ids: list[int],
    os_event_ids: list[int] | None = None,
):
    """Read frame data from DB, call Claude Agent SDK, store episodes."""
    if not screen_ids and not audio_ids and not os_event_ids:
        return

    conn = _get_conn()
    try:
        # Budget check
        if not check_daily_budget(conn, DAILY_COST_CAP_USD):
            logger.warning("process_episode: daily budget exceeded, skipping")
            return

        frames = _load_frames(conn, screen_ids, audio_ids, os_event_ids)
        if not frames:
            return

        logger.info(
            "process_episode: %d frames [%s -> %s]",
            len(frames), frames[0].timestamp, frames[-1].timestamp,
        )

        prompt = _build_prompt(frames)

        # LLM call with validation + retry
        last_resp = [None]  # mutable container for closure

        def _call_llm(retry_prompt):
            p = retry_prompt if retry_prompt else prompt
            resp = _llm.complete(p, MODEL_FAST)
            last_resp[0] = resp
            return resp.text

        tasks = with_retry(_call_llm, validate_episodes, max_retries=1)
        resp = last_resp[0]

        _store_episodes(conn, tasks, frames)

        # Record usage + log
        cost = resp.cost_usd or 0
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (MODEL_FAST, "episode", resp.input_tokens, resp.output_tokens, cost),
        )
        conn.execute(
            "INSERT INTO pipeline_logs (stage, prompt, response, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("episode", prompt, resp.text, MODEL_FAST, resp.input_tokens, resp.output_tokens, cost),
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


# -- Daily playbook distillation --


@huey.periodic_task(crontab(hour="3", minute="0"))
def daily_distill_task():
    """Daily playbook distillation with Opus. Runs every day at 3am."""
    conn = _get_conn()
    try:
        # Budget check
        if not check_daily_budget(conn, DAILY_COST_CAP_USD):
            logger.warning("daily distill: daily budget exceeded, skipping")
            return

        episodes = conn.execute(
            "SELECT * FROM episodes WHERE created_at >= datetime('now', '-1 days') "
            "ORDER BY created_at",
        ).fetchall()

        if not episodes:
            logger.info("daily distill: no episodes, skipping")
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

        # LLM call with validation + retry
        last_resp = [None]

        def _call_llm(retry_prompt):
            p = retry_prompt if retry_prompt else prompt
            resp = _llm.complete(p, MODEL_DEEP)
            last_resp[0] = resp
            return resp.text

        entries = with_retry(_call_llm, validate_playbooks, max_retries=1)
        resp = last_resp[0]

        cost = resp.cost_usd or 0
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (MODEL_DEEP, "distill", resp.input_tokens, resp.output_tokens, cost),
        )
        conn.execute(
            "INSERT INTO pipeline_logs (stage, prompt, response, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("distill", prompt, resp.text, MODEL_DEEP, resp.input_tokens, resp.output_tokens, cost),
        )

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
            "daily distill: %d entries from %d episodes, cost=$%.4f",
            count, len(episodes), cost,
        )

    except Exception:
        logger.exception("daily distill failed")
    finally:
        conn.close()


# -- Daily routine extraction (runs after distill) --


@huey.periodic_task(crontab(hour="3", minute="30"))
def daily_routines_task():
    """Daily routine extraction with Opus. Runs at 3:30am (after distill at 3am)."""
    conn = _get_conn()
    try:
        if not check_daily_budget(conn, DAILY_COST_CAP_USD):
            logger.warning("daily routines: daily budget exceeded, skipping")
            return

        episodes = conn.execute(
            "SELECT * FROM episodes WHERE created_at >= datetime('now', '-1 days') "
            "ORDER BY created_at",
        ).fetchall()

        if not episodes:
            logger.info("daily routines: no episodes, skipping")
            return

        playbooks = conn.execute(
            "SELECT * FROM playbook_entries ORDER BY confidence DESC",
        ).fetchall()

        existing_routines = conn.execute(
            "SELECT * FROM routines ORDER BY confidence DESC",
        ).fetchall()

        episodes_text = "\n\n".join(
            f"Episode #{e['id']} ({e['started_at']} to {e['ended_at']}):\n{e['summary']}"
            for e in episodes
        )

        playbooks_text = (
            "\n".join(
                f"- **{p['name']}** ({p['confidence']:.1f}): {p['context']} → {p['action']}"
                for p in playbooks
            )
            if playbooks
            else "(no playbook entries yet)"
        )

        routines_text = (
            "\n\n".join(
                f"- **{r['name']}** (confidence: {r['confidence']}, maturity: {r['maturity']})\n"
                f"  Trigger: {r['trigger']}\n  Goal: {r['goal']}\n"
                f"  Steps: {r['steps']}\n  Uses: {r['uses']}"
                for r in existing_routines
            )
            if existing_routines
            else "(none yet)"
        )

        prompt = ROUTINE_PROMPT.format(
            playbooks=playbooks_text, routines=routines_text, episodes=episodes_text,
        )

        resp = _llm.complete(prompt, MODEL_DEEP)
        cost = resp.cost_usd or 0

        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (MODEL_DEEP, "routines", resp.input_tokens, resp.output_tokens, cost),
        )
        conn.execute(
            "INSERT INTO pipeline_logs (stage, prompt, response, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("routines", prompt, resp.text, MODEL_DEEP, resp.input_tokens, resp.output_tokens, cost),
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
            conn.execute(
                "INSERT INTO routines (name, trigger, goal, steps, uses, confidence, maturity, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(name) DO UPDATE SET "
                "trigger=excluded.trigger, goal=excluded.goal, steps=excluded.steps, "
                "uses=excluded.uses, confidence=excluded.confidence, maturity=excluded.maturity, "
                "updated_at=datetime('now')",
                (
                    entry["name"],
                    entry.get("trigger", ""),
                    entry.get("goal", ""),
                    json.dumps(entry.get("steps", []), ensure_ascii=False),
                    json.dumps(entry.get("uses", []), ensure_ascii=False),
                    entry.get("confidence", 0.4),
                    entry.get("maturity", "nascent"),
                ),
            )
            count += 1

        conn.commit()
        logger.info(
            "daily routines: %d routines from %d episodes, cost=$%.4f",
            count, len(episodes), cost,
        )

    except Exception:
        logger.exception("daily routines failed")
    finally:
        conn.close()


# -- Weekly garbage collection --

GC_PROMPT = """You are the garbage collection agent for a behavioral playbook system.

You have two jobs:

## 1. Playbook quality audit
Review playbook entries for quality issues and clean up as needed.
Tools: find_similar_pairs, check_evidence_exists, check_maturity_consistency,
record_snapshot, merge_entries, deprecate_entry.

Process:
- Check maturity consistency issues
- Look for similar pairs that might need merging
- Investigate with check_evidence_exists
- Take action: merge duplicates, deprecate invalid entries
- Always record_snapshot before modifying an entry
- Be conservative — when in doubt, leave entries alone

## 2. Raw data management
Manage disk/DB usage by cleaning up old processed data.
Tools: get_data_stats, get_oldest_processed, purge_processed_frames,
purge_processed_audio, purge_processed_os_events, purge_pipeline_logs.

Process:
- First call get_data_stats to see how much data exists
- Then call get_oldest_processed to see how old it is
- Based on the volume and age, decide what to purge and how aggressively
- Only purge processed data (already extracted into episodes)
- Keep enough recent data for debugging (at least a few days)
- Pipeline logs can be more aggressively purged since they're debug-only

Output a brief summary of what you did when finished."""


@huey.periodic_task(crontab(hour="4", minute="0"))
def daily_gc_task():
    """Daily garbage collection: decay + agent-driven audit. Runs every day at 4am (after distill at 3am)."""
    from engine.pipeline.decay import decay_confidence
    from engine.pipeline.dedup import make_dedup_tools
    from engine.pipeline.audit import make_audit_tools

    conn = _get_conn()
    try:
        # Budget check
        if not check_daily_budget(conn, DAILY_COST_CAP_USD):
            logger.warning("daily_gc: daily budget exceeded, skipping")
            return

        # Phase 1: Deterministic decay
        decayed = decay_confidence(conn)
        logger.info("daily_gc: decayed %d entries", decayed)

        # Phase 2: Agent-driven audit (only if LLM supports tools)
        gc_tools = make_dedup_tools(conn) + make_audit_tools(conn)
        try:
            resp = _llm.complete_with_tools(
                GC_PROMPT, MODEL_DEEP, gc_tools, max_turns=10,
            )
            cost = resp.cost_usd or 0
            conn.execute(
                "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?)",
                (MODEL_DEEP, "gc", resp.input_tokens, resp.output_tokens, cost),
            )
            conn.execute(
                "INSERT INTO pipeline_logs (stage, prompt, response, model, input_tokens, output_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("gc", GC_PROMPT, resp.text, MODEL_DEEP, resp.input_tokens, resp.output_tokens, cost),
            )
            conn.commit()
            logger.info("daily_gc: agent audit complete, cost=$%.4f", cost)
        except NotImplementedError:
            logger.info("daily_gc: LLM client does not support tools, skipping agent audit")

    except Exception:
        logger.exception("daily_gc failed")
    finally:
        conn.close()
