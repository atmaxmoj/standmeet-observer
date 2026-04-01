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

from engine.config import Settings, DAILY_COST_CAP_USD
from engine.domain.observation.filter import should_keep, detect_windows
from engine.infrastructure.pipeline.budget import check_daily_budget
from engine.infrastructure.pipeline.orchestrator import run_episode, run_distill, run_routines

logger = logging.getLogger(__name__)

_settings = None


def _get_settings():
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_huey():
    s = _get_settings()
    return SqliteHuey(filename=str(Path(s.huey_db_dir) / "huey.db"))


huey = _get_huey()


def _get_session():
    """Get a SQLAlchemy session for ORM operations."""
    from engine.infrastructure.persistence.engine import get_sync_session_factory
    factory = get_sync_session_factory(_get_settings().database_url_sync)
    return factory()


# -- Triggered by ingest: check if pending frames form complete windows --


_KNOWN_SOURCES = {"capture", "audio", "os_event"}


def _enqueue_window(window: list):
    """Extract IDs from a window and enqueue process_episode."""
    screen_ids = [f.id for f in window if f.source == "capture"]
    audio_ids = [f.id for f in window if f.source == "audio"]
    os_event_ids = [f.id for f in window if f.source == "os_event"]
    window_source_ids: dict[str, list[int]] = {}
    for f in window:
        if f.source not in _KNOWN_SOURCES:
            window_source_ids.setdefault(f.source, []).append(f.id)
    process_episode(screen_ids, audio_ids, os_event_ids, window_source_ids or None)


def _mark_all_processed(session, screen_ids, audio_ids, os_ids, source_ids, registry, remainder):
    """Mark frames as processed, excluding remainder."""
    from engine.infrastructure.etl.repository import mark_source_processed
    remainder_ids = {f.id for f in remainder}
    _mark_processed(session, screen_ids - remainder_ids, audio_ids - remainder_ids, os_ids - remainder_ids)
    if registry and source_ids:
        remainder_by_source: dict[str, set[int]] = {}
        for f in remainder:
            if f.source not in _KNOWN_SOURCES:
                remainder_by_source.setdefault(f.source, set()).add(f.id)
        mark_source_processed(session, registry, {
            name: ids - remainder_by_source.get(name, set())
            for name, ids in source_ids.items()
        })


@huey.task()
@huey.lock_task("pipeline-check")
def on_new_data():
    """Check unprocessed frames for complete windows. Deduplicated by lock."""
    session = _get_session()
    try:
        from engine.infrastructure.etl.repository import load_unprocessed_frames, load_unprocessed_source_frames
        from engine.infrastructure.etl.sources.manifest_registry import get_global_registry
        screen_frames, audio_frames, os_frames = load_unprocessed_frames(session)

        registry = get_global_registry()
        source_frames_dict = load_unprocessed_source_frames(session, registry) if registry else {}

        logger.info(
            "on_new_data: screen=%d audio=%d os=%d registry=%s sources=%s",
            len(screen_frames), len(audio_frames), len(os_frames),
            registry is not None, {k: len(v) for k, v in source_frames_dict.items()} if source_frames_dict else {},
        )

        if not screen_frames and not audio_frames and not os_frames and not source_frames_dict:
            return

        all_raw = screen_frames + audio_frames + os_frames
        for fl in source_frames_dict.values():
            all_raw.extend(fl)

        all_screen_ids = {f.id for f in screen_frames}
        all_audio_ids = {f.id for f in audio_frames}
        all_os_ids = {f.id for f in os_frames}
        all_source_ids: dict[str, set[int]] = {
            name: {f.id for f in fl} for name, fl in source_frames_dict.items()
        }

        kept = sorted([f for f in all_raw if should_keep(f)], key=lambda f: f.timestamp)

        if not kept:
            logger.info("on_new_data: all %d frames filtered as noise, marking processed", len(all_raw))
            _mark_all_processed(session, all_screen_ids, all_audio_ids, all_os_ids, all_source_ids, registry, [])
            return

        windows, remainder = detect_windows(kept, window_minutes=30, idle_seconds=_get_settings().idle_threshold_seconds)

        if not windows:
            logger.info("on_new_data: %d frames, no complete windows, %d remainder", len(all_raw), len(remainder))
            return

        logger.info("on_new_data: %d windows from %d frames (%d remainder)", len(windows), len(all_raw), len(remainder))

        for window in windows:
            _enqueue_window(window)

        _mark_all_processed(session, all_screen_ids, all_audio_ids, all_os_ids, all_source_ids, registry, remainder)

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
    from engine.infrastructure.etl.repository import mark_processed
    mark_processed(session, screen_ids, audio_ids, os_event_ids)


# -- Process a window: read full data from DB by IDs, call Haiku --


@huey.task(retries=2, retry_delay=30)
def process_episode(
    screen_ids: list[int],
    audio_ids: list[int],
    os_event_ids: list[int] | None = None,
    source_ids: dict[str, list[int]] | None = None,
):
    """Read frame data from DB, call LLM, store episodes."""
    if not screen_ids and not audio_ids and not os_event_ids and not source_ids:
        return
    session = _get_session()
    try:
        if not check_daily_budget(session, DAILY_COST_CAP_USD):
            logger.warning("process_episode: budget exceeded, skipping")
            return
        tasks, count = run_episode(_get_settings(), session, screen_ids, audio_ids, os_event_ids, source_ids=source_ids)
        session.commit()
        logger.info("process_episode: %d episodes created", count)
    except Exception:
        logger.exception("process_episode FAILED (screen=%d, audio=%d, os=%d, sources=%s)",
                         len(screen_ids), len(audio_ids), len(os_event_ids or []),
                         list((source_ids or {}).keys()))
    finally:
        session.close()


# -- Daily DA (Personal Data Analyst) — runs FIRST so distill/compose can reference insights --


@huey.periodic_task(crontab(hour="3", minute="0"))
def daily_da_task():
    """Daily DA insights generation. Runs at 3am before distill/compose."""
    from engine.infrastructure.pipeline.orchestrator import run_da

    session = _get_session()
    try:
        if not check_daily_budget(session, DAILY_COST_CAP_USD):
            logger.warning("daily DA: budget exceeded, skipping")
            return
        count = run_da(_get_settings(), session)
        session.commit()
        logger.info("daily DA: %d insights", count)
    except Exception:
        logger.exception("daily DA FAILED")
    finally:
        session.close()


# -- Daily playbook distillation (runs after DA) --


@huey.periodic_task(crontab(hour="3", minute="30"))
def daily_distill_task():
    """Daily playbook distillation with Opus. Runs at 3:30am after DA."""
    session = _get_session()
    try:
        if not check_daily_budget(session, DAILY_COST_CAP_USD):
            logger.warning("daily distill: budget exceeded, skipping")
            return
        count = run_distill(_get_settings(), session)
        session.commit()
        logger.info("daily distill: %d entries updated", count)
    except Exception:
        logger.exception("daily distill FAILED")
    finally:
        session.close()


# -- Daily routine extraction (runs after distill) --


@huey.periodic_task(crontab(hour="4", minute="0"))
def daily_routines_task():
    """Daily routine extraction with Opus. Runs at 4am."""
    session = _get_session()
    try:
        if not check_daily_budget(session, DAILY_COST_CAP_USD):
            logger.warning("daily routines: budget exceeded, skipping")
            return
        count = run_routines(_get_settings(), session)
        session.commit()
        logger.info("daily routines: %d routines updated", count)
    except Exception:
        logger.exception("daily routines FAILED")
    finally:
        session.close()


# -- Daily garbage collection --


@huey.periodic_task(crontab(hour="4", minute="30"))
def daily_gc_task():
    """Daily garbage collection: decay + agent-driven audit. Runs at 4:30am."""
    from engine.application.gc import run_gc

    session = _get_session()
    try:
        from engine.infrastructure.persistence.sync_db import SyncDB
        db = SyncDB(session)
        if db.get_state_int("gc_disabled"):
            logger.info("daily GC: disabled by user, skipping")
            return
        run_gc(_get_settings(), session)
    except Exception:
        logger.exception("daily_gc failed")
    finally:
        session.close()
