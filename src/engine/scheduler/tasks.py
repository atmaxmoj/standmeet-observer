"""Huey task queue for behavioral distillation pipeline.

Queue-native design:
- Ingest endpoints push lightweight signals to queue (no data, just "check now")
- on_new_data: reads unprocessed frames from DB, detects windows, enqueues episodes
- process_episode: receives frame IDs, reads full data from DB, calls LLM
- DB owns all data + progress tracking (processed column)
"""

import logging
from pathlib import Path

from huey import SqliteHuey, crontab

from engine.config import Settings, MODEL_DEEP, DAILY_COST_CAP_USD
from engine.llm import create_client
from engine.etl.filter import should_keep, detect_windows
from engine.pipeline.budget import check_daily_budget
from engine.pipeline.orchestrator import run_episode, run_distill, run_routines

logger = logging.getLogger(__name__)

settings = Settings()

huey = SqliteHuey(
    filename=str(Path(settings.huey_db_dir) / "huey.db"),
)

_llm = create_client(
    api_key=settings.anthropic_api_key,
    auth_token=settings.claude_code_oauth_token,
    openai_api_key=settings.openai_api_key,
    openai_base_url=settings.openai_base_url,
)


def _get_session():
    """Get a SQLAlchemy session for ORM operations."""
    from engine.storage.engine import get_sync_session_factory
    factory = get_sync_session_factory(settings.database_url_sync)
    return factory()


# -- Triggered by ingest: check if pending frames form complete windows --


@huey.task()
@huey.lock_task("pipeline-check")
def on_new_data():
    """Check unprocessed frames for complete windows. Deduplicated by lock."""
    session = _get_session()
    try:
        from engine.etl.repository import load_unprocessed_frames
        screen_frames, audio_frames, os_frames = load_unprocessed_frames(session)

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
        filtered_count = len(all_raw) - len(kept)

        if not kept:
            logger.info(
                "on_new_data: all %d frames filtered as noise (%d screen, %d audio, %d os), marking processed",
                len(all_raw), len(screen_frames), len(audio_frames), len(os_frames),
            )
            _mark_processed(session, all_screen_ids, all_audio_ids, all_os_ids)
            return

        # Detect windows
        windows, remainder = detect_windows(
            kept,
            window_minutes=30,
            idle_seconds=settings.idle_threshold_seconds,
        )

        if not windows:
            time_range = f"{kept[0].timestamp} → {kept[-1].timestamp}" if kept else "?"
            logger.info(
                "on_new_data: %d frames (%d kept, %d noise), no complete windows. "
                "Time range: %s, remainder: %d",
                len(all_raw), len(kept), filtered_count, time_range, len(remainder),
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
            session,
            all_screen_ids - remainder_ids,
            all_audio_ids - remainder_ids,
            all_os_ids - remainder_ids,
        )

    except Exception:
        logger.exception("on_new_data failed")
    finally:
        session.close()


def _mark_processed(
    session,
    screen_ids: set[int],
    audio_ids: set[int],
    os_event_ids: set[int] | None = None,
):
    """Mark frames as processed in DB."""
    from engine.etl.repository import mark_processed
    mark_processed(session, screen_ids, audio_ids, os_event_ids)


# -- Process a window: read full data from DB by IDs, call Haiku --


@huey.task(retries=2, retry_delay=30)
def process_episode(
    screen_ids: list[int],
    audio_ids: list[int],
    os_event_ids: list[int] | None = None,
):
    """Read frame data from DB, call LLM, store episodes."""
    if not screen_ids and not audio_ids and not os_event_ids:
        return
    session = _get_session()
    try:
        if not check_daily_budget(session, DAILY_COST_CAP_USD):
            logger.warning("process_episode: budget exceeded, skipping")
            return
        tasks, count = run_episode(_llm, session, screen_ids, audio_ids, os_event_ids)
        session.commit()
        logger.info("process_episode: %d episodes created", count)
    except Exception:
        logger.exception("process_episode FAILED (screen=%d, audio=%d, os=%d)",
                         len(screen_ids), len(audio_ids), len(os_event_ids or []))
    finally:
        session.close()


# -- Daily playbook distillation --


@huey.periodic_task(crontab(hour="3", minute="0"))
def daily_distill_task():
    """Daily playbook distillation with Opus. Runs every day at 3am."""
    session = _get_session()
    try:
        if not check_daily_budget(session, DAILY_COST_CAP_USD):
            logger.warning("daily distill: budget exceeded, skipping")
            return
        count = run_distill(_llm, session)
        session.commit()
        logger.info("daily distill: %d entries updated", count)
    except Exception:
        logger.exception("daily distill FAILED")
    finally:
        session.close()


# -- Daily routine extraction (runs after distill) --


@huey.periodic_task(crontab(hour="3", minute="30"))
def daily_routines_task():
    """Daily routine extraction with Opus. Runs at 3:30am."""
    session = _get_session()
    try:
        if not check_daily_budget(session, DAILY_COST_CAP_USD):
            logger.warning("daily routines: budget exceeded, skipping")
            return
        count = run_routines(_llm, session)
        session.commit()
        logger.info("daily routines: %d routines updated", count)
    except Exception:
        logger.exception("daily routines FAILED")
    finally:
        session.close()


# -- Weekly garbage collection --

GC_PROMPT = """You are the garbage collection agent for a behavioral playbook system.

You have three jobs:

## 1. CRITICAL: Sensitive data detection and purge
Screen captures (frames) may contain passwords, API keys, tokens, secrets, or other
sensitive information visible on screen. This is a SECURITY issue — purge aggressively.

Process:
- Call search_frames_for_sensitive to scan for common secret patterns
- IF any sensitive frames found THEN purge them immediately regardless of age
- This takes priority over ALL other GC tasks

## 2. Playbook quality audit
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

## 3. Raw data management
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
    from engine.pipeline.decay import decay_confidence, decay_routines
    from engine.agents.tools.dedup import make_dedup_tools
    from engine.agents.tools.audit import make_audit_tools

    session = _get_session()
    try:
        # Budget check
        if not check_daily_budget(session, DAILY_COST_CAP_USD):
            logger.warning("daily_gc: daily budget exceeded, skipping")
            return

        # Phase 1: Deterministic decay
        decayed_pb = decay_confidence(session)
        decayed_rt = decay_routines(session)
        logger.info("daily_gc: decayed %d playbook entries, %d routines", decayed_pb, decayed_rt)

        # Phase 2: Agent-driven audit (only if LLM supports tools)
        gc_tools = make_dedup_tools(session) + make_audit_tools(session)
        try:
            resp = _llm.complete_with_tools(
                GC_PROMPT, MODEL_DEEP, gc_tools, max_turns=10,
            )
            from engine.storage.sync_db import SyncDB
            cost = resp.cost_usd or 0
            db = SyncDB(session)
            db.record_usage(MODEL_DEEP, "gc", resp.input_tokens, resp.output_tokens, cost)
            db.insert_pipeline_log("gc", GC_PROMPT, resp.text, MODEL_DEEP, resp.input_tokens, resp.output_tokens, cost)
            session.commit()
            logger.info("daily_gc: agent audit complete, cost=$%.4f", cost)
        except NotImplementedError:
            logger.info("daily_gc: LLM client does not support tools, skipping agent audit")

    except Exception:
        logger.exception("daily_gc failed")
    finally:
        session.close()
