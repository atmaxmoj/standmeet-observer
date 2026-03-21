"""Integration test: simulate the full pipeline trigger chain.

Tests on_new_data logic directly (without Huey decorators):
ingest frames -> read unprocessed -> detect windows -> mark processed -> enqueue IDs
"""

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from engine.infrastructure.persistence.models import Base
from engine.domain.observation.entity import Frame
from engine.domain.observation.filter import should_keep, detect_windows
from tests.conftest import TEST_PG_SYNC


@pytest.fixture
def conn(_test_schema):
    """Create a real PostgreSQL session with the engine schema."""
    url = f"{TEST_PG_SYNC}?options=-csearch_path%3D{_test_schema}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()
    engine.dispose()


def _simulate_on_new_data(conn, idle_seconds=300, window_minutes=30):
    """
    Simulate the on_new_data task logic: read unprocessed -> filter -> detect windows -> mark.
    Returns list of (screen_ids, audio_ids) that would be enqueued to process_episode.
    """
    # Read unprocessed screen frames
    screen_rows = conn.execute(
        text("SELECT id, timestamp, app_name, window_name, text, image_path "
             "FROM frames WHERE processed = 0 ORDER BY timestamp LIMIT 500"),
    ).mappings().all()
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

    # Read unprocessed audio frames
    audio_rows = conn.execute(
        text("SELECT id, timestamp, text, language "
             "FROM audio_frames WHERE processed = 0 ORDER BY timestamp LIMIT 100"),
    ).mappings().all()
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
        return []

    all_raw = screen_frames + audio_frames
    all_screen_ids = {f.id for f in screen_frames}
    all_audio_ids = {f.id for f in audio_frames}

    # Filter noise + sort
    kept = sorted(
        [f for f in all_raw if should_keep(f)],
        key=lambda f: f.timestamp,
    )

    if not kept:
        # All noise -- mark everything processed
        _mark_processed(conn, all_screen_ids, all_audio_ids)
        return []

    # Detect windows
    windows, remainder = detect_windows(
        kept,
        window_minutes=window_minutes,
        idle_seconds=idle_seconds,
    )

    if not windows:
        return []

    # Collect what would be enqueued
    enqueued = []
    for window in windows:
        screen_ids = [f.id for f in window if f.source == "capture"]
        audio_ids = [f.id for f in window if f.source == "audio"]
        enqueued.append((screen_ids, audio_ids))

    # Mark everything EXCEPT remainder as processed
    remainder_ids = {f.id for f in remainder}
    _mark_processed(
        conn,
        all_screen_ids - remainder_ids,
        all_audio_ids - remainder_ids,
    )

    return enqueued


def _mark_processed(conn, screen_ids, audio_ids):
    if screen_ids:
        ph = ",".join(str(i) for i in screen_ids)
        conn.execute(text(f"UPDATE frames SET processed = 1 WHERE id IN ({ph})"))
    if audio_ids:
        ph = ",".join(str(i) for i in audio_ids)
        conn.execute(text(f"UPDATE audio_frames SET processed = 1 WHERE id IN ({ph})"))
    conn.commit()


def _count(conn, table, processed):
    return conn.execute(
        text(f"SELECT COUNT(*) as c FROM {table} WHERE processed = :p"),
        {"p": processed},
    ).scalar()


def _insert_frames(conn, count, minutes_ago, app="VSCode", window="editor.py"):
    base = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    for i in range(count):
        t = (base + timedelta(minutes=i)).isoformat()
        conn.execute(
            text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                 "VALUES (:ts, :app, :win, :txt, 1, :hash)"),
            {"ts": t, "app": app, "win": window,
             "txt": f"meaningful content line number {i} here", "hash": f"h{i}"},
        )
    conn.commit()


class TestPipelineTrigger:
    def test_old_frames_trigger_window(self, conn):
        """Frames older than idle_seconds -> window triggered, frames marked processed."""
        _insert_frames(conn, count=10, minutes_ago=60)
        assert _count(conn, "frames", 0) == 10

        enqueued = _simulate_on_new_data(conn, idle_seconds=300)

        assert len(enqueued) >= 1, "Should trigger at least 1 window"
        screen_ids, audio_ids = enqueued[0]
        assert len(screen_ids) > 0
        assert _count(conn, "frames", 1) > 0, "Frames should be marked processed"

    def test_recent_frames_stay_unprocessed(self, conn):
        """Frames from just now -> no window, all stay unprocessed."""
        now = datetime.now(timezone.utc)
        for i in range(3):
            t = (now - timedelta(seconds=i * 2)).isoformat()
            conn.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'Terminal', 'zsh', :txt, 1, :hash)"),
                {"ts": t, "txt": f"recent command number {i} text content", "hash": f"r{i}"},
            )
        conn.commit()

        enqueued = _simulate_on_new_data(conn, idle_seconds=300)

        assert len(enqueued) == 0, "No window for recent frames"
        assert _count(conn, "frames", 0) == 3, "All should remain unprocessed"

    def test_mixed_old_and_recent(self, conn):
        """Old frames get processed, recent frames stay as remainder."""
        _insert_frames(conn, count=5, minutes_ago=60)

        now = datetime.now(timezone.utc)
        for i in range(3):
            t = (now - timedelta(seconds=i * 2)).isoformat()
            conn.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'Terminal', 'zsh', :txt, 1, :hash)"),
                {"ts": t, "txt": f"recent command number {i} with text", "hash": f"r{i}"},
            )
        conn.commit()

        enqueued = _simulate_on_new_data(conn, idle_seconds=300)

        assert len(enqueued) >= 1
        assert _count(conn, "frames", 1) > 0, "Old frames processed"
        assert _count(conn, "frames", 0) > 0, "Recent frames remain"

    def test_noise_marked_processed(self, conn):
        """Noise frames (Finder, short text) are marked processed, not stuck forever."""
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                 "VALUES (:ts, 'Finder', 'Desktop', 'x', 1, 'n1')"), {"ts": old},
        )
        conn.execute(
            text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                 "VALUES (:ts, 'Dock', '', '', 1, 'n2')"), {"ts": old},
        )
        conn.commit()

        enqueued = _simulate_on_new_data(conn, idle_seconds=300)

        assert len(enqueued) == 0, "Noise should not trigger window"
        assert _count(conn, "frames", 1) == 2, "Noise frames should be marked processed"

    def test_audio_frames_included(self, conn):
        """Audio frames are picked up and included in windows."""
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        for i in range(5):
            t = (old + timedelta(minutes=i)).isoformat()
            conn.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'VSCode', 'main.py', :txt, 1, :hash)"),
                {"ts": t, "txt": f"code line number {i} with enough text", "hash": f"h{i}"},
            )
        for i in range(2):
            t = (old + timedelta(minutes=i)).isoformat()
            conn.execute(
                text("INSERT INTO audio_frames (timestamp, text, language, duration_seconds) "
                     "VALUES (:ts, :txt, 'en', 3.0)"),
                {"ts": t, "txt": f"spoken text number {i} with content"},
            )
        conn.commit()

        enqueued = _simulate_on_new_data(conn, idle_seconds=300)

        assert len(enqueued) >= 1
        screen_ids, audio_ids = enqueued[0]
        assert len(screen_ids) > 0, "Should include screen frames"
        assert len(audio_ids) > 0, "Should include audio frames"
        assert _count(conn, "frames", 1) > 0
        assert _count(conn, "audio_frames", 1) > 0

    def test_idle_gap_splits_windows(self, conn):
        """A big gap between frames -> separate windows."""
        old = datetime.now(timezone.utc) - timedelta(hours=2)

        # Group 1: 3 frames close together
        for i in range(3):
            t = (old + timedelta(seconds=i * 10)).isoformat()
            conn.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'VSCode', 'a.py', :txt, 1, :hash)"),
                {"ts": t, "txt": f"code content group one line {i}", "hash": f"g1_{i}"},
            )
        # Gap of 30 minutes -> exceeds 5-min idle threshold
        for i in range(3):
            t = (old + timedelta(minutes=30, seconds=i * 10)).isoformat()
            conn.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'Chrome', 'docs', :txt, 1, :hash)"),
                {"ts": t, "txt": f"reading docs group two line {i}", "hash": f"g2_{i}"},
            )
        conn.commit()

        enqueued = _simulate_on_new_data(conn, idle_seconds=300)

        assert len(enqueued) == 2, f"Expected 2 windows (idle gap split), got {len(enqueued)}"
        assert len(enqueued[0][0]) == 3  # Group 1
        assert len(enqueued[1][0]) == 3  # Group 2

    def test_second_run_skips_processed(self, conn):
        """Running on_new_data again should skip already-processed frames."""
        _insert_frames(conn, count=5, minutes_ago=60)

        # First run processes everything
        enqueued1 = _simulate_on_new_data(conn, idle_seconds=300)
        assert len(enqueued1) >= 1

        # Second run: nothing new
        enqueued2 = _simulate_on_new_data(conn, idle_seconds=300)
        assert len(enqueued2) == 0, "No new data, should not trigger"

    def test_new_frames_after_processing(self, conn):
        """New frames added after first run should be picked up."""
        _insert_frames(conn, count=5, minutes_ago=120)
        _simulate_on_new_data(conn, idle_seconds=300)

        # Add more old frames
        base = datetime.now(timezone.utc) - timedelta(minutes=30)
        for i in range(3):
            t = (base + timedelta(minutes=i)).isoformat()
            conn.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'Terminal', 'zsh', :txt, 1, :hash)"),
                {"ts": t, "txt": f"new batch command number {i} content", "hash": f"new{i}"},
            )
        conn.commit()

        enqueued = _simulate_on_new_data(conn, idle_seconds=300)
        assert len(enqueued) >= 1, "New frames should trigger a new window"

    def test_process_episode_receives_correct_ids(self, conn):
        """process_episode gets exactly the frame IDs in the window."""
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        inserted_ids = []
        for i in range(5):
            t = (old + timedelta(minutes=i)).isoformat()
            result = conn.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'VSCode', 'main.py', :txt, 1, :hash) RETURNING id"),
                {"ts": t, "txt": f"code content for episode test line {i}", "hash": f"ep{i}"},
            )
            inserted_ids.append(result.scalar())
        conn.commit()

        enqueued = _simulate_on_new_data(conn, idle_seconds=300)

        assert len(enqueued) == 1
        screen_ids, _ = enqueued[0]
        assert sorted(screen_ids) == sorted(inserted_ids)
