"""Tests for raw capture data recall tools."""

import sqlite3
import pytest
from engine.agents.repository import (
    get_recent_frames,
    get_frames_by_app,
    get_recent_audio,
    get_recent_os_events,
    get_os_events_by_type,
)


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE IF NOT EXISTS frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            app_name TEXT NOT NULL DEFAULT '',
            window_name TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            display_id INTEGER NOT NULL DEFAULT 0,
            image_hash TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            processed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS audio_frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            duration_seconds REAL NOT NULL DEFAULT 0.0,
            text TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'mic',
            chunk_path TEXT NOT NULL DEFAULT '',
            processed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS os_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            data TEXT NOT NULL DEFAULT '',
            processed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    c.commit()
    yield c
    c.close()


class TestGetRecentFrames:
    def test_empty(self, conn):
        assert get_recent_frames(conn, hours=24) == []

    def test_returns_recent(self, conn):
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, window_name, text) "
            "VALUES (?, ?, ?, ?)",
            ("2026-03-16T10:00:00Z", "VSCode", "main.py", "def hello():"),
        )
        conn.commit()
        results = get_recent_frames(conn, hours=24)
        assert len(results) == 1
        assert results[0]["app_name"] == "VSCode"

    def test_excludes_old(self, conn):
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, text, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("t1", "VSCode", "old", "2020-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, text) VALUES (?, ?, ?)",
            ("t2", "Chrome", "new"),
        )
        conn.commit()
        results = get_recent_frames(conn, hours=24)
        assert len(results) == 1
        assert results[0]["app_name"] == "Chrome"

    def test_limit(self, conn):
        for i in range(20):
            conn.execute(
                "INSERT INTO frames (timestamp, app_name, text) VALUES (?, ?, ?)",
                (f"t{i}", "app", f"text {i}"),
            )
        conn.commit()
        results = get_recent_frames(conn, hours=24, limit=5)
        assert len(results) == 5

    def test_truncates_text(self, conn):
        long_text = "x" * 1000
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, text) VALUES (?, ?, ?)",
            ("t1", "app", long_text),
        )
        conn.commit()
        results = get_recent_frames(conn, hours=24)
        assert len(results[0]["text"]) <= 300


class TestGetFramesByApp:
    def test_empty(self, conn):
        assert get_frames_by_app(conn, "VSCode") == []

    def test_filters(self, conn):
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, text) VALUES (?, ?, ?)",
            ("t1", "VSCode", "code"),
        )
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, text) VALUES (?, ?, ?)",
            ("t2", "Chrome", "browse"),
        )
        conn.commit()
        results = get_frames_by_app(conn, "VSCode")
        assert len(results) == 1
        assert results[0]["text"] == "code"

    def test_partial_match(self, conn):
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, text) VALUES (?, ?, ?)",
            ("t1", "Visual Studio Code", "code"),
        )
        conn.commit()
        results = get_frames_by_app(conn, "Visual Studio")
        assert len(results) == 1


class TestGetRecentAudio:
    def test_empty(self, conn):
        assert get_recent_audio(conn, hours=24) == []

    def test_returns_recent(self, conn):
        conn.execute(
            "INSERT INTO audio_frames (timestamp, text, language, duration_seconds) "
            "VALUES (?, ?, ?, ?)",
            ("t1", "hello world", "en", 5.0),
        )
        conn.commit()
        results = get_recent_audio(conn, hours=24)
        assert len(results) == 1
        assert results[0]["text"] == "hello world"
        assert results[0]["language"] == "en"

    def test_excludes_old(self, conn):
        conn.execute(
            "INSERT INTO audio_frames (timestamp, text, created_at) VALUES (?, ?, ?)",
            ("t1", "old", "2020-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO audio_frames (timestamp, text) VALUES (?, ?)",
            ("t2", "new"),
        )
        conn.commit()
        results = get_recent_audio(conn, hours=24)
        assert len(results) == 1
        assert results[0]["text"] == "new"


class TestGetRecentOsEvents:
    def test_empty(self, conn):
        assert get_recent_os_events(conn, hours=24) == []

    def test_returns_recent(self, conn):
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, source, data) "
            "VALUES (?, ?, ?, ?)",
            ("t1", "shell", "zsh", "git status"),
        )
        conn.commit()
        results = get_recent_os_events(conn, hours=24)
        assert len(results) == 1
        assert results[0]["data"] == "git status"

    def test_excludes_old(self, conn):
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, data, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("t1", "shell", "old cmd", "2020-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, data) VALUES (?, ?, ?)",
            ("t2", "url", "new url"),
        )
        conn.commit()
        results = get_recent_os_events(conn, hours=24)
        assert len(results) == 1


class TestGetOsEventsByType:
    def test_empty(self, conn):
        assert get_os_events_by_type(conn, "shell") == []

    def test_filters(self, conn):
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, data) VALUES (?, ?, ?)",
            ("t1", "shell", "git status"),
        )
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, data) VALUES (?, ?, ?)",
            ("t2", "url", "https://github.com"),
        )
        conn.commit()
        results = get_os_events_by_type(conn, "shell")
        assert len(results) == 1
        assert results[0]["data"] == "git status"

    def test_limit(self, conn):
        for i in range(30):
            conn.execute(
                "INSERT INTO os_events (timestamp, event_type, data) VALUES (?, ?, ?)",
                (f"t{i}", "shell", f"cmd {i}"),
            )
        conn.commit()
        results = get_os_events_by_type(conn, "shell", limit=10)
        assert len(results) == 10
