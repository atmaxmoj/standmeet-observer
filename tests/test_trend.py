"""Tests for playbook trend query tools."""

import sqlite3
import pytest
from engine.agents.repository import get_playbook_history, get_stale_entries, get_similar_entries


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE IF NOT EXISTS playbook_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            context TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.0,
            maturity TEXT NOT NULL DEFAULT 'nascent',
            evidence TEXT NOT NULL DEFAULT '[]',
            last_evidence_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS playbook_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playbook_name TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            maturity TEXT NOT NULL DEFAULT 'nascent',
            evidence TEXT NOT NULL DEFAULT '[]',
            change_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    c.commit()
    yield c
    c.close()


def _insert_playbook(conn, name, confidence=0.5, maturity="nascent", evidence="[]",
                      last_evidence_at=None, context=""):
    conn.execute(
        "INSERT INTO playbook_entries (name, context, confidence, maturity, evidence, last_evidence_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, context, confidence, maturity, evidence, last_evidence_at),
    )
    conn.commit()


def _insert_history(conn, name, confidence, maturity="nascent", evidence="[]",
                     change_reason="", created_at=None):
    if created_at:
        conn.execute(
            "INSERT INTO playbook_history (playbook_name, confidence, maturity, evidence, change_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, confidence, maturity, evidence, change_reason, created_at),
        )
    else:
        conn.execute(
            "INSERT INTO playbook_history (playbook_name, confidence, maturity, evidence, change_reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, confidence, maturity, evidence, change_reason),
        )
    conn.commit()


class TestGetPlaybookHistory:
    def test_empty(self, conn):
        assert get_playbook_history(conn, "nonexistent") == []

    def test_returns_history(self, conn):
        _insert_history(conn, "morning-coding", 0.3, "nascent", change_reason="initial")
        _insert_history(conn, "morning-coding", 0.6, "developing", change_reason="new evidence")
        history = get_playbook_history(conn, "morning-coding")
        assert len(history) == 2
        assert history[0]["confidence"] == 0.3
        assert history[1]["confidence"] == 0.6

    def test_filters_by_name(self, conn):
        _insert_history(conn, "morning-coding", 0.5)
        _insert_history(conn, "evening-browsing", 0.3)
        assert len(get_playbook_history(conn, "morning-coding")) == 1


class TestGetStaleEntries:
    def test_empty_db(self, conn):
        assert get_stale_entries(conn, days=14) == []

    def test_no_evidence_date_is_stale(self, conn):
        _insert_playbook(conn, "old-pattern", last_evidence_at=None)
        results = get_stale_entries(conn, days=14)
        assert len(results) == 1
        assert results[0]["name"] == "old-pattern"

    def test_recent_evidence_not_stale(self, conn):
        _insert_playbook(conn, "fresh-pattern", last_evidence_at="2099-01-01T00:00:00Z")
        results = get_stale_entries(conn, days=14)
        assert len(results) == 0

    def test_old_evidence_is_stale(self, conn):
        _insert_playbook(conn, "old-pattern", last_evidence_at="2020-01-01T00:00:00Z")
        results = get_stale_entries(conn, days=14)
        assert len(results) == 1


class TestGetSimilarEntries:
    def test_empty_db(self, conn):
        assert get_similar_entries(conn, "morning-coding") == []

    def test_finds_similar_names(self, conn):
        _insert_playbook(conn, "morning-coding")
        _insert_playbook(conn, "afternoon-coding")
        _insert_playbook(conn, "morning-browsing")
        _insert_playbook(conn, "evening-gaming")

        # "morning-coding" words: {morning, coding}
        results = get_similar_entries(conn, "morning-coding")
        names = [r["name"] for r in results]
        # afternoon-coding shares "coding" (similarity = 1/3 ≈ 0.33)
        # morning-browsing shares "morning" (similarity = 1/3 ≈ 0.33)
        assert "afternoon-coding" in names
        assert "morning-browsing" in names
        # evening-gaming shares nothing
        assert "evening-gaming" not in names

    def test_similarity_score_included(self, conn):
        _insert_playbook(conn, "morning-coding")
        _insert_playbook(conn, "morning-coding-session")
        results = get_similar_entries(conn, "morning-coding")
        assert len(results) == 1
        assert "similarity" in results[0]
        assert results[0]["similarity"] > 0.3

    def test_excludes_self(self, conn):
        _insert_playbook(conn, "morning-coding")
        results = get_similar_entries(conn, "morning-coding")
        assert len(results) == 0
