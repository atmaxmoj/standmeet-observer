"""Tests for POST /engine/backfill endpoint.

Verifies:
1. Backfill resets frames to unprocessed, detects windows, enqueues episodes
2. Returns correct window count and frame stats
3. All frames marked processed after backfill
4. process_episode called with correct IDs
5. Audio frames included alongside screen frames
6. Empty DB returns 0 windows
7. Noise-only frames return 0 windows, all marked processed
8. OS events don't participate in window detection
"""

import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from engine.api.routes import router


@pytest.fixture(autouse=True)
def mock_engine_tasks():
    """Mock engine.tasks and engine.scheduler.tasks to avoid SqliteHuey module-level init.

    Saves/restores real modules if already loaded (avoids contaminating other test files).
    """
    mock_process = MagicMock()
    mock_mod = ModuleType("engine.tasks")
    mock_mod.process_episode = mock_process
    mock_mod.on_new_data = MagicMock()

    mock_scheduler_mod = ModuleType("engine.scheduler.tasks")
    mock_scheduler_mod.process_episode = mock_process
    mock_scheduler_mod.on_new_data = MagicMock()

    originals = {
        "engine.tasks": sys.modules.get("engine.tasks"),
        "engine.scheduler.tasks": sys.modules.get("engine.scheduler.tasks"),
    }
    sys.modules["engine.tasks"] = mock_mod
    sys.modules["engine.scheduler.tasks"] = mock_scheduler_mod
    yield mock_process
    for key, original in originals.items():
        if original is not None:
            sys.modules[key] = original
        else:
            sys.modules.pop(key, None)


@pytest.fixture
def app(db):
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.db = db
    test_app.state.llm = MagicMock()
    test_app.state.settings = MagicMock()
    test_app.state.settings.frames_base_dir = "/tmp/frames"
    return test_app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def patch_settings(db):
    """Patch Settings so backfill uses the test DB path."""
    mock_settings = MagicMock()
    mock_settings.return_value.database_url_sync = f"sqlite:///{db.path}"
    mock_settings.return_value.anthropic_api_key = ""
    mock_settings.return_value.claude_code_oauth_token = ""
    mock_settings.return_value.openai_api_key = ""
    mock_settings.return_value.openai_base_url = ""
    mock_settings.return_value.idle_threshold_seconds = 300
    with patch("engine.config.Settings", mock_settings):
        yield


def _insert_screen_frames(db_path: str, count: int, minutes_ago: int, gap_seconds: int = 60):
    """Insert screen frames directly via sync sqlite3 (matching backfill's DB access)."""
    conn = sqlite3.connect(db_path)
    base = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ids = []
    for i in range(count):
        t = (base + timedelta(seconds=i * gap_seconds)).isoformat()
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (t, "VSCode", "editor.py", f"meaningful code content line {i} here", f"h{i}"),
        )
        ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    conn.close()
    return ids


def _insert_audio_frames(db_path: str, count: int, minutes_ago: int):
    conn = sqlite3.connect(db_path)
    base = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ids = []
    for i in range(count):
        t = (base + timedelta(minutes=i)).isoformat()
        conn.execute(
            "INSERT INTO audio_frames (timestamp, text, language, duration_seconds) "
            "VALUES (?, ?, 'en', 3.0)",
            (t, f"spoken words number {i} with content"),
        )
        ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    conn.close()
    return ids


def _insert_os_events(db_path: str, count: int, minutes_ago: int):
    conn = sqlite3.connect(db_path)
    base = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ids = []
    for i in range(count):
        t = (base + timedelta(minutes=i)).isoformat()
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, source, data) "
            "VALUES (?, ?, ?, ?)",
            (t, "shell_command", "zsh", f"git commit -m 'change number {i}'"),
        )
        ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    conn.close()
    return ids


def _count_processed(db_path: str, table: str, processed: int) -> int:
    conn = sqlite3.connect(db_path)
    c = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE processed = ?", (processed,)).fetchone()[0]
    conn.close()
    return c


def _mark_all_processed(db_path: str):
    """Pre-mark frames as processed (to verify backfill resets them)."""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE frames SET processed = 1")
    conn.execute("UPDATE audio_frames SET processed = 1")
    conn.commit()
    conn.close()


@pytest.mark.asyncio
class TestBackfillEndpoint:

    async def test_empty_db_returns_zero(self, client, db, mock_engine_tasks):
        resp = await client.post("/engine/backfill")

        assert resp.status_code == 200
        data = resp.json()
        assert data["windows"] == 0
        mock_engine_tasks.assert_not_called()

    async def test_screen_frames_produce_windows(self, client, db, mock_engine_tasks):
        _insert_screen_frames(db.path, count=10, minutes_ago=60)

        resp = await client.post("/engine/backfill")

        assert resp.status_code == 200
        data = resp.json()
        assert data["windows"] >= 1
        assert data["total_frames"] == 10
        assert data["kept_frames"] == 10
        assert mock_engine_tasks.call_count == data["windows"]

    async def test_all_frames_marked_processed(self, client, db):
        _insert_screen_frames(db.path, count=10, minutes_ago=60)

        await client.post("/engine/backfill")

        assert _count_processed(db.path, "frames", 1) == 10
        assert _count_processed(db.path, "frames", 0) == 0

    async def test_resets_already_processed_frames(self, client, db, mock_engine_tasks):
        """Backfill should reset processed=1 frames back to 0, then reprocess all."""
        _insert_screen_frames(db.path, count=5, minutes_ago=60)
        _mark_all_processed(db.path)

        assert _count_processed(db.path, "frames", 1) == 5

        resp = await client.post("/engine/backfill")

        data = resp.json()
        assert data["windows"] >= 1
        assert data["total_frames"] == 5
        assert mock_engine_tasks.call_count >= 1

    async def test_process_episode_receives_correct_ids(self, client, db, mock_engine_tasks):
        inserted_ids = _insert_screen_frames(db.path, count=5, minutes_ago=60, gap_seconds=10)

        await client.post("/engine/backfill")

        # Collect all screen IDs passed to process_episode
        all_screen_ids = []
        for call in mock_engine_tasks.call_args_list:
            screen_ids = call[0][0]
            all_screen_ids.extend(screen_ids)

        assert sorted(all_screen_ids) == sorted(inserted_ids)

    async def test_audio_frames_included(self, client, db, mock_engine_tasks):
        _insert_screen_frames(db.path, count=5, minutes_ago=60)
        audio_ids = _insert_audio_frames(db.path, count=3, minutes_ago=60)

        resp = await client.post("/engine/backfill")

        data = resp.json()
        assert data["total_frames"] == 8
        assert data["windows"] >= 1

        # Collect all audio IDs passed to process_episode
        all_audio_ids = []
        for call in mock_engine_tasks.call_args_list:
            a_ids = call[0][1]
            all_audio_ids.extend(a_ids)

        assert sorted(all_audio_ids) == sorted(audio_ids)

        # Audio frames also marked processed
        assert _count_processed(db.path, "audio_frames", 1) == 3

    async def test_noise_only_returns_zero_windows(self, client, db, mock_engine_tasks):
        """All-noise frames → 0 windows, but all marked processed."""
        conn = sqlite3.connect(db.path)
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
            "VALUES (?, 'Finder', 'Desktop', 'x', 1, 'n1')", (old,),
        )
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
            "VALUES (?, 'Dock', '', '', 1, 'n2')", (old,),
        )
        conn.commit()
        conn.close()

        resp = await client.post("/engine/backfill")

        data = resp.json()
        assert data["windows"] == 0
        assert _count_processed(db.path, "frames", 1) == 2
        mock_engine_tasks.assert_not_called()

    async def test_idle_gap_splits_into_multiple_windows(self, client, db):
        """Two clusters separated by >5min idle → 2+ windows."""
        conn = sqlite3.connect(db.path)
        # Group 1: 2 hours ago
        base1 = datetime.now(timezone.utc) - timedelta(hours=2)
        for i in range(5):
            t = (base1 + timedelta(seconds=i * 10)).isoformat()
            conn.execute(
                "INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                "VALUES (?, 'VSCode', 'a.py', ?, 1, ?)",
                (t, f"group one code content line {i}", f"g1_{i}"),
            )
        # Group 2: 30 min ago (big gap from group 1)
        base2 = datetime.now(timezone.utc) - timedelta(minutes=30)
        for i in range(5):
            t = (base2 + timedelta(seconds=i * 10)).isoformat()
            conn.execute(
                "INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                "VALUES (?, 'Chrome', 'docs', ?, 1, ?)",
                (t, f"group two reading docs line {i}", f"g2_{i}"),
            )
        conn.commit()
        conn.close()

        resp = await client.post("/engine/backfill")

        data = resp.json()
        assert data["windows"] >= 2, f"Expected 2+ windows from idle gap, got {data['windows']}"
        assert data["total_frames"] == 10

    async def test_remainder_included_as_window(self, client, db, mock_engine_tasks):
        """Backfill should force-close remainder (unlike normal pipeline)."""
        # Insert recent frames that would normally be remainder
        conn = sqlite3.connect(db.path)
        now = datetime.now(timezone.utc)
        for i in range(5):
            t = (now - timedelta(seconds=i * 2)).isoformat()
            conn.execute(
                "INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                "VALUES (?, 'Terminal', 'zsh', ?, 1, ?)",
                (t, f"recent meaningful command number {i}", f"r{i}"),
            )
        conn.commit()
        conn.close()

        resp = await client.post("/engine/backfill")

        data = resp.json()
        # Backfill appends remainder as a window, so these should be processed
        assert data["windows"] >= 1, "Backfill should force-close remainder into a window"
        assert mock_engine_tasks.call_count >= 1

    async def test_os_events_participate_in_idle_detection(self, client, db, mock_engine_tasks):
        """OS events fill idle gaps — all three sources mixed in window detection."""
        _insert_screen_frames(db.path, count=5, minutes_ago=60)
        _insert_os_events(db.path, count=3, minutes_ago=60)

        resp = await client.post("/engine/backfill")

        data = resp.json()
        assert data["total_frames"] == 8  # 5 screen + 3 os_events
        assert data["windows"] >= 1
