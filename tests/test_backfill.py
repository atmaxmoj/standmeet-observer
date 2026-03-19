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

import sys
from datetime import datetime, timezone, timedelta
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from engine.api.routes import router
from tests.conftest import TEST_PG_SYNC


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
def sync_engine(_test_schema):
    """Create a sync SQLAlchemy engine connected to the test schema."""
    url = f"{TEST_PG_SYNC}?options=-csearch_path%3D{_test_schema}"
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def app(db, _test_schema, sync_engine):
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
def patch_settings(db, _test_schema):
    """Patch Settings so backfill uses the test DB."""
    sync_url = f"{TEST_PG_SYNC}?options=-csearch_path%3D{_test_schema}"
    mock_settings = MagicMock()
    mock_settings.return_value.database_url_sync = sync_url
    mock_settings.return_value.anthropic_api_key = ""
    mock_settings.return_value.claude_code_oauth_token = ""
    mock_settings.return_value.openai_api_key = ""
    mock_settings.return_value.openai_base_url = ""
    mock_settings.return_value.idle_threshold_seconds = 300
    with patch("engine.config.Settings", mock_settings):
        yield


def _get_sync_session(_test_schema):
    """Get a sync session for direct DB operations."""
    url = f"{TEST_PG_SYNC}?options=-csearch_path%3D{_test_schema}"
    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    session = factory()
    return session, engine


def _insert_screen_frames(_test_schema, count: int, minutes_ago: int, gap_seconds: int = 60):
    """Insert screen frames directly via sync session."""
    session, engine = _get_sync_session(_test_schema)
    base = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ids = []
    for i in range(count):
        t = (base + timedelta(seconds=i * gap_seconds)).isoformat()
        result = session.execute(
            text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                 "VALUES (:ts, :app, :win, :txt, 1, :hash) RETURNING id"),
            {"ts": t, "app": "VSCode", "win": "editor.py",
             "txt": f"meaningful code content line {i} here", "hash": f"h{i}"},
        )
        ids.append(result.scalar())
    session.commit()
    session.close()
    engine.dispose()
    return ids


def _insert_audio_frames(_test_schema, count: int, minutes_ago: int):
    session, engine = _get_sync_session(_test_schema)
    base = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ids = []
    for i in range(count):
        t = (base + timedelta(minutes=i)).isoformat()
        result = session.execute(
            text("INSERT INTO audio_frames (timestamp, text, language, duration_seconds) "
                 "VALUES (:ts, :txt, 'en', 3.0) RETURNING id"),
            {"ts": t, "txt": f"spoken words number {i} with content"},
        )
        ids.append(result.scalar())
    session.commit()
    session.close()
    engine.dispose()
    return ids


def _insert_os_events(_test_schema, count: int, minutes_ago: int):
    session, engine = _get_sync_session(_test_schema)
    base = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ids = []
    for i in range(count):
        t = (base + timedelta(minutes=i)).isoformat()
        result = session.execute(
            text("INSERT INTO os_events (timestamp, event_type, source, data) "
                 "VALUES (:ts, :etype, :src, :data) RETURNING id"),
            {"ts": t, "etype": "shell_command", "src": "zsh",
             "data": f"git commit -m 'change number {i}'"},
        )
        ids.append(result.scalar())
    session.commit()
    session.close()
    engine.dispose()
    return ids


def _count_processed(_test_schema, table: str, processed: int) -> int:
    session, engine = _get_sync_session(_test_schema)
    c = session.execute(
        text(f"SELECT COUNT(*) FROM {table} WHERE processed = :p"),
        {"p": processed},
    ).scalar()
    session.close()
    engine.dispose()
    return c


def _mark_all_processed(_test_schema):
    """Pre-mark frames as processed (to verify backfill resets them)."""
    session, engine = _get_sync_session(_test_schema)
    session.execute(text("UPDATE frames SET processed = 1"))
    session.execute(text("UPDATE audio_frames SET processed = 1"))
    session.commit()
    session.close()
    engine.dispose()


@pytest.mark.asyncio
class TestBackfillEndpoint:

    async def test_empty_db_returns_zero(self, client, db, mock_engine_tasks):
        resp = await client.post("/engine/backfill")

        assert resp.status_code == 200
        data = resp.json()
        assert data["windows"] == 0
        mock_engine_tasks.assert_not_called()

    async def test_screen_frames_produce_windows(self, client, db, _test_schema, mock_engine_tasks):
        _insert_screen_frames(_test_schema, count=10, minutes_ago=60)

        resp = await client.post("/engine/backfill")

        assert resp.status_code == 200
        data = resp.json()
        assert data["windows"] >= 1
        assert data["total_frames"] == 10
        assert data["kept_frames"] == 10
        assert mock_engine_tasks.call_count == data["windows"]

    async def test_all_frames_marked_processed(self, client, db, _test_schema):
        _insert_screen_frames(_test_schema, count=10, minutes_ago=60)

        await client.post("/engine/backfill")

        assert _count_processed(_test_schema, "frames", 1) == 10
        assert _count_processed(_test_schema, "frames", 0) == 0

    async def test_resets_already_processed_frames(self, client, db, _test_schema, mock_engine_tasks):
        """Backfill should reset processed=1 frames back to 0, then reprocess all."""
        _insert_screen_frames(_test_schema, count=5, minutes_ago=60)
        _mark_all_processed(_test_schema)

        assert _count_processed(_test_schema, "frames", 1) == 5

        resp = await client.post("/engine/backfill")

        data = resp.json()
        assert data["windows"] >= 1
        assert data["total_frames"] == 5
        assert mock_engine_tasks.call_count >= 1

    async def test_process_episode_receives_correct_ids(self, client, db, _test_schema, mock_engine_tasks):
        inserted_ids = _insert_screen_frames(_test_schema, count=5, minutes_ago=60, gap_seconds=10)

        await client.post("/engine/backfill")

        # Collect all screen IDs passed to process_episode
        all_screen_ids = []
        for call in mock_engine_tasks.call_args_list:
            screen_ids = call[0][0]
            all_screen_ids.extend(screen_ids)

        assert sorted(all_screen_ids) == sorted(inserted_ids)

    async def test_audio_frames_included(self, client, db, _test_schema, mock_engine_tasks):
        _insert_screen_frames(_test_schema, count=5, minutes_ago=60)
        audio_ids = _insert_audio_frames(_test_schema, count=3, minutes_ago=60)

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
        assert _count_processed(_test_schema, "audio_frames", 1) == 3

    async def test_noise_only_returns_zero_windows(self, client, db, _test_schema, mock_engine_tasks):
        """All-noise frames -> 0 windows, but all marked processed."""
        session, engine = _get_sync_session(_test_schema)
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        session.execute(
            text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                 "VALUES (:ts, 'Finder', 'Desktop', 'x', 1, 'n1')"), {"ts": old},
        )
        session.execute(
            text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                 "VALUES (:ts, 'Dock', '', '', 1, 'n2')"), {"ts": old},
        )
        session.commit()
        session.close()
        engine.dispose()

        resp = await client.post("/engine/backfill")

        data = resp.json()
        assert data["windows"] == 0
        assert _count_processed(_test_schema, "frames", 1) == 2
        mock_engine_tasks.assert_not_called()

    async def test_idle_gap_splits_into_multiple_windows(self, client, db, _test_schema):
        """Two clusters separated by >5min idle -> 2+ windows."""
        session, engine = _get_sync_session(_test_schema)
        # Group 1: 2 hours ago
        base1 = datetime.now(timezone.utc) - timedelta(hours=2)
        for i in range(5):
            t = (base1 + timedelta(seconds=i * 10)).isoformat()
            session.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'VSCode', 'a.py', :txt, 1, :hash)"),
                {"ts": t, "txt": f"group one code content line {i}", "hash": f"g1_{i}"},
            )
        # Group 2: 30 min ago (big gap from group 1)
        base2 = datetime.now(timezone.utc) - timedelta(minutes=30)
        for i in range(5):
            t = (base2 + timedelta(seconds=i * 10)).isoformat()
            session.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'Chrome', 'docs', :txt, 1, :hash)"),
                {"ts": t, "txt": f"group two reading docs line {i}", "hash": f"g2_{i}"},
            )
        session.commit()
        session.close()
        engine.dispose()

        resp = await client.post("/engine/backfill")

        data = resp.json()
        assert data["windows"] >= 2, f"Expected 2+ windows from idle gap, got {data['windows']}"
        assert data["total_frames"] == 10

    async def test_remainder_included_as_window(self, client, db, _test_schema, mock_engine_tasks):
        """Backfill should force-close remainder (unlike normal pipeline)."""
        # Insert recent frames that would normally be remainder
        session, engine = _get_sync_session(_test_schema)
        now = datetime.now(timezone.utc)
        for i in range(5):
            t = (now - timedelta(seconds=i * 2)).isoformat()
            session.execute(
                text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash) "
                     "VALUES (:ts, 'Terminal', 'zsh', :txt, 1, :hash)"),
                {"ts": t, "txt": f"recent meaningful command number {i}", "hash": f"r{i}"},
            )
        session.commit()
        session.close()
        engine.dispose()

        resp = await client.post("/engine/backfill")

        data = resp.json()
        # Backfill appends remainder as a window, so these should be processed
        assert data["windows"] >= 1, "Backfill should force-close remainder into a window"
        assert mock_engine_tasks.call_count >= 1

    async def test_os_events_participate_in_idle_detection(self, client, db, _test_schema, mock_engine_tasks):
        """OS events fill idle gaps -- all three sources mixed in window detection."""
        _insert_screen_frames(_test_schema, count=5, minutes_ago=60)
        _insert_os_events(_test_schema, count=3, minutes_ago=60)

        resp = await client.post("/engine/backfill")

        data = resp.json()
        assert data["total_frames"] == 8  # 5 screen + 3 os_events
        assert data["windows"] >= 1
