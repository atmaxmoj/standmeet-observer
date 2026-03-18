"""Tests for evidence audit tools + playbook snapshots."""

import json
import sqlite3
import pytest
from engine.agents.repository import (
    check_evidence_exists,
    check_maturity_consistency,
    record_snapshot,
    deprecate_entry,
)


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


def _insert_playbook(conn, name, confidence=0.5, maturity="nascent", evidence="[]"):
    conn.execute(
        "INSERT INTO playbook_entries (name, confidence, maturity, evidence) VALUES (?, ?, ?, ?)",
        (name, confidence, maturity, evidence),
    )
    conn.commit()


def _insert_episode(conn, episode_id=None):
    conn.execute(
        "INSERT INTO episodes (summary, started_at, ended_at) VALUES (?, ?, ?)",
        ("test episode", "t1", "t2"),
    )
    conn.commit()


class TestCheckEvidenceExists:
    def test_entry_not_found(self, conn):
        result = check_evidence_exists(conn, "nonexistent")
        assert "error" in result

    def test_empty_evidence(self, conn):
        _insert_playbook(conn, "test-entry", evidence="[]")
        result = check_evidence_exists(conn, "test-entry")
        assert result["all_exist"] is True
        assert result["missing"] == []

    def test_all_evidence_exists(self, conn):
        # Insert 3 episodes
        for _ in range(3):
            _insert_episode(conn)
        _insert_playbook(conn, "test-entry", evidence="[1, 2, 3]")
        result = check_evidence_exists(conn, "test-entry")
        assert result["all_exist"] is True
        assert result["missing"] == []

    def test_orphan_evidence(self, conn):
        _insert_episode(conn)  # id=1
        _insert_playbook(conn, "test-entry", evidence="[1, 99, 100]")
        result = check_evidence_exists(conn, "test-entry")
        assert result["all_exist"] is False
        assert set(result["missing"]) == {99, 100}


class TestCheckMaturityConsistency:
    def test_empty_db(self, conn):
        assert check_maturity_consistency(conn) == []

    def test_consistent_entries(self, conn):
        _insert_playbook(conn, "nascent-entry", maturity="nascent", evidence="[1]")
        _insert_playbook(conn, "developing-ok", maturity="developing", evidence="[1,2,3]")
        assert check_maturity_consistency(conn) == []

    def test_mature_with_few_evidence(self, conn):
        _insert_playbook(conn, "bad-mature", maturity="mature", evidence="[1, 2]")
        results = check_maturity_consistency(conn)
        assert len(results) == 1
        assert results[0]["name"] == "bad-mature"
        assert "mature" in results[0]["issue"]

    def test_developing_with_few_evidence(self, conn):
        _insert_playbook(conn, "bad-developing", maturity="developing", evidence="[1]")
        results = check_maturity_consistency(conn)
        assert len(results) == 1

    def test_mastered_with_enough_evidence(self, conn):
        evidence = json.dumps(list(range(1, 11)))
        _insert_playbook(conn, "good-mastered", maturity="mastered", evidence=evidence)
        assert check_maturity_consistency(conn) == []


class TestRecordSnapshot:
    def test_records_snapshot(self, conn):
        _insert_playbook(conn, "test-entry", confidence=0.7, maturity="developing")
        result = record_snapshot(conn, "test-entry", reason="before merge")
        assert result["name"] == "test-entry"
        assert result["snapshot_confidence"] == 0.7

        history = conn.execute(
            "SELECT * FROM playbook_history WHERE playbook_name = ?",
            ("test-entry",),
        ).fetchall()
        assert len(history) == 1
        assert history[0]["change_reason"] == "before merge"

    def test_not_found(self, conn):
        result = record_snapshot(conn, "nonexistent")
        assert "error" in result


class TestDeprecateEntry:
    def test_deprecates(self, conn):
        _insert_playbook(conn, "old-pattern", confidence=0.8, maturity="mature")
        result = deprecate_entry(conn, 1, reason="superseded")
        assert result["deprecated"] is True

        row = conn.execute("SELECT * FROM playbook_entries WHERE id = 1").fetchone()
        assert row["confidence"] == 0.0
        assert row["maturity"] == "nascent"

        # Should have recorded a snapshot
        history = conn.execute("SELECT * FROM playbook_history").fetchall()
        assert len(history) == 1
        assert "superseded" in history[0]["change_reason"]

    def test_not_found(self, conn):
        result = deprecate_entry(conn, 999)
        assert "error" in result
