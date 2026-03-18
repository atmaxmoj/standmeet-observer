"""Tests for playbook deduplication tools."""

import sqlite3
import pytest
from engine.agents.repository import find_similar_pairs, merge_entries


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


def _insert(conn, name, confidence=0.5, evidence="[]", context=""):
    conn.execute(
        "INSERT INTO playbook_entries (name, context, confidence, evidence) VALUES (?, ?, ?, ?)",
        (name, context, confidence, evidence),
    )
    conn.commit()


class TestFindSimilarPairs:
    def test_empty_db(self, conn):
        assert find_similar_pairs(conn) == []

    def test_no_similar(self, conn):
        _insert(conn, "morning-coding")
        _insert(conn, "evening-gaming")
        assert find_similar_pairs(conn) == []

    def test_finds_high_similarity(self, conn):
        _insert(conn, "morning-coding", confidence=0.8)
        _insert(conn, "morning-coding-session", confidence=0.5)
        pairs = find_similar_pairs(conn, threshold=0.5)
        assert len(pairs) == 1
        assert pairs[0]["similarity"] >= 0.5

    def test_identical_words(self, conn):
        # These share 2/3 words ("deep" and "focus")
        _insert(conn, "deep-focus-coding")
        _insert(conn, "deep-focus-reading")
        pairs = find_similar_pairs(conn, threshold=0.5)
        assert len(pairs) == 1

    def test_threshold_filtering(self, conn):
        _insert(conn, "morning-coding")
        _insert(conn, "morning-browsing")
        # Jaccard of {morning, coding} vs {morning, browsing} = 1/3 ≈ 0.33
        assert find_similar_pairs(conn, threshold=0.8) == []
        assert len(find_similar_pairs(conn, threshold=0.3)) == 1


class TestMergeEntries:
    def test_basic_merge(self, conn):
        _insert(conn, "entry-a", confidence=0.8, evidence="[1, 2, 3]")
        _insert(conn, "entry-b", confidence=0.6, evidence="[3, 4, 5]")

        result = merge_entries(conn, keep_id=1, remove_id=2)
        assert result["kept"] == "entry-a"
        assert result["removed"] == "entry-b"
        assert result["new_confidence"] == 0.8
        assert result["merged_evidence"] == [1, 2, 3, 4, 5]

        # entry-b should be deleted
        remaining = conn.execute("SELECT * FROM playbook_entries").fetchall()
        assert len(remaining) == 1
        assert remaining[0]["name"] == "entry-a"

    def test_keeps_higher_confidence(self, conn):
        _insert(conn, "entry-a", confidence=0.3, evidence="[1]")
        _insert(conn, "entry-b", confidence=0.9, evidence="[2]")

        result = merge_entries(conn, keep_id=1, remove_id=2)
        assert result["new_confidence"] == 0.9

    def test_deduplicates_evidence(self, conn):
        _insert(conn, "entry-a", evidence="[1, 2, 3]")
        _insert(conn, "entry-b", evidence="[2, 3, 4]")

        result = merge_entries(conn, keep_id=1, remove_id=2)
        assert result["merged_evidence"] == [1, 2, 3, 4]

    def test_missing_entry(self, conn):
        _insert(conn, "entry-a")
        result = merge_entries(conn, keep_id=1, remove_id=999)
        assert "error" in result

    def test_empty_evidence(self, conn):
        _insert(conn, "entry-a", evidence="[]")
        _insert(conn, "entry-b", evidence="[]")
        result = merge_entries(conn, keep_id=1, remove_id=2)
        assert result["merged_evidence"] == []
