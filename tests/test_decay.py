"""Tests for confidence time decay."""

import sqlite3
from datetime import datetime, timedelta, timezone
import pytest
from engine.pipeline.decay import decay_confidence


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
    c.commit()
    yield c
    c.close()


def _insert(conn, name, confidence, last_evidence_at=None):
    conn.execute(
        "INSERT INTO playbook_entries (name, confidence, last_evidence_at) VALUES (?, ?, ?)",
        (name, confidence, last_evidence_at),
    )
    conn.commit()


class TestDecayConfidence:
    def test_empty_db(self, conn):
        assert decay_confidence(conn) == 0

    def test_recent_evidence_no_decay(self, conn):
        recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        _insert(conn, "fresh-entry", 0.8, last_evidence_at=recent)
        assert decay_confidence(conn) == 0
        row = conn.execute("SELECT confidence FROM playbook_entries").fetchone()
        assert row["confidence"] == 0.8

    def test_old_evidence_decays(self, conn):
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=45)).isoformat()
        _insert(conn, "old-entry", 0.8, last_evidence_at=old)
        assert decay_confidence(conn) == 1
        row = conn.execute("SELECT confidence FROM playbook_entries").fetchone()
        # 45 days: factor = max(0.3, 1.0 - 45/90) = 0.5
        assert abs(row["confidence"] - 0.4) < 0.01

    def test_very_old_hits_floor(self, conn):
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=180)).isoformat()
        _insert(conn, "ancient-entry", 0.8, last_evidence_at=old)
        assert decay_confidence(conn) == 1
        row = conn.execute("SELECT confidence FROM playbook_entries").fetchone()
        # > 90 days: factor = 0.3 (floor)
        assert abs(row["confidence"] - 0.24) < 0.01  # 0.8 * 0.3

    def test_no_evidence_date_max_decay(self, conn):
        _insert(conn, "no-evidence", 0.8, last_evidence_at=None)
        assert decay_confidence(conn) == 1
        row = conn.execute("SELECT confidence FROM playbook_entries").fetchone()
        # No evidence date: days_since = 90, factor = 0.3 (floor)
        assert abs(row["confidence"] - 0.24) < 0.01

    def test_multiple_entries(self, conn):
        recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)).isoformat()
        _insert(conn, "fresh", 0.8, last_evidence_at=recent)
        _insert(conn, "stale", 0.6, last_evidence_at=old)
        updated = decay_confidence(conn)
        assert updated == 1  # only stale one decayed

    def test_decay_math_30_days(self, conn):
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)).isoformat()
        _insert(conn, "entry", 1.0, last_evidence_at=old)
        decay_confidence(conn)
        row = conn.execute("SELECT confidence FROM playbook_entries").fetchone()
        # 30 days: factor = max(0.3, 1.0 - 30/90) = 0.6667
        expected = 1.0 * (1.0 - 30 / 90)
        assert abs(row["confidence"] - expected) < 0.01
