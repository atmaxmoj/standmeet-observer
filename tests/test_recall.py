"""Tests for episode recall tools."""

import sqlite3
import pytest
from engine.agents.repository import search_episodes, get_recent_episodes, get_episodes_by_app


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary TEXT NOT NULL,
            app_names TEXT NOT NULL DEFAULT '',
            frame_count INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            frame_id_min INTEGER NOT NULL DEFAULT 0,
            frame_id_max INTEGER NOT NULL DEFAULT 0,
            frame_source TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    c.commit()
    yield c
    c.close()


def _insert_episode(conn, summary, app_names="[]", started_at="2026-03-15T10:00:00Z",
                     ended_at="2026-03-15T10:30:00Z", created_at=None):
    if created_at:
        conn.execute(
            "INSERT INTO episodes (summary, app_names, started_at, ended_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (summary, app_names, started_at, ended_at, created_at),
        )
    else:
        conn.execute(
            "INSERT INTO episodes (summary, app_names, started_at, ended_at) "
            "VALUES (?, ?, ?, ?)",
            (summary, app_names, started_at, ended_at),
        )
    conn.commit()


class TestSearchEpisodes:
    def test_empty_db(self, conn):
        assert search_episodes(conn, "coding") == []

    def test_finds_matching(self, conn):
        _insert_episode(conn, "Writing Python code in VSCode")
        _insert_episode(conn, "Browsing Reddit in Chrome")
        results = search_episodes(conn, "Python")
        assert len(results) == 1
        assert "Python" in results[0]["summary"]

    def test_case_insensitive_like(self, conn):
        _insert_episode(conn, "Writing Python code")
        results = search_episodes(conn, "python")
        # SQLite LIKE is case-insensitive for ASCII
        assert len(results) == 1

    def test_limit(self, conn):
        for i in range(10):
            _insert_episode(conn, f"coding session {i}")
        results = search_episodes(conn, "coding", limit=3)
        assert len(results) == 3

    def test_no_match(self, conn):
        _insert_episode(conn, "Writing Python code")
        assert search_episodes(conn, "golang") == []


class TestGetRecentEpisodes:
    def test_empty_db(self, conn):
        assert get_recent_episodes(conn, hours=24) == []

    def test_recent_episodes_returned(self, conn):
        _insert_episode(conn, "Recent work")
        results = get_recent_episodes(conn, hours=24)
        assert len(results) == 1

    def test_old_episodes_excluded(self, conn):
        _insert_episode(conn, "Old work", created_at="2020-01-01T00:00:00Z")
        _insert_episode(conn, "Recent work")
        results = get_recent_episodes(conn, hours=24)
        assert len(results) == 1
        assert results[0]["summary"] == "Recent work"


class TestGetEpisodesByApp:
    def test_empty_db(self, conn):
        assert get_episodes_by_app(conn, "VSCode") == []

    def test_filters_by_app(self, conn):
        _insert_episode(conn, "Coding", app_names='["VSCode"]')
        _insert_episode(conn, "Browsing", app_names='["Chrome"]')
        results = get_episodes_by_app(conn, "VSCode")
        assert len(results) == 1
        assert results[0]["summary"] == "Coding"

    def test_partial_match(self, conn):
        _insert_episode(conn, "Coding", app_names='["Visual Studio Code"]')
        results = get_episodes_by_app(conn, "Visual Studio")
        assert len(results) == 1
