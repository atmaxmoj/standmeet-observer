"""Tests for playbook deduplication tools."""

import pytest
from engine.infrastructure.persistence.models import PlaybookEntry
from engine.infrastructure.agent.repository import find_similar_pairs, merge_entries


@pytest.fixture
def session(sync_session):
    return sync_session


def _insert(session, name, confidence=0.5, evidence="[]", context=""):
    session.add(PlaybookEntry(name=name, context=context, confidence=confidence, evidence=evidence))
    session.commit()


class TestFindSimilarPairs:
    def test_empty_db(self, session):
        assert find_similar_pairs(session) == []

    def test_no_similar(self, session):
        _insert(session, "morning-coding")
        _insert(session, "evening-gaming")
        assert find_similar_pairs(session) == []

    def test_finds_high_similarity(self, session):
        _insert(session, "morning-coding", confidence=0.8)
        _insert(session, "morning-coding-session", confidence=0.5)
        pairs = find_similar_pairs(session, threshold=0.5)
        assert len(pairs) == 1
        assert pairs[0]["similarity"] >= 0.5

    def test_identical_words(self, session):
        # These share 2/3 words ("deep" and "focus")
        _insert(session, "deep-focus-coding")
        _insert(session, "deep-focus-reading")
        pairs = find_similar_pairs(session, threshold=0.5)
        assert len(pairs) == 1

    def test_threshold_filtering(self, session):
        _insert(session, "morning-coding")
        _insert(session, "morning-browsing")
        # Jaccard of {morning, coding} vs {morning, browsing} = 1/3 ~ 0.33
        assert find_similar_pairs(session, threshold=0.8) == []
        assert len(find_similar_pairs(session, threshold=0.3)) == 1


class TestMergeEntries:
    def test_basic_merge(self, session):
        _insert(session, "entry-a", confidence=0.8, evidence="[1, 2, 3]")
        _insert(session, "entry-b", confidence=0.6, evidence="[3, 4, 5]")

        result = merge_entries(session, keep_id=1, remove_id=2)
        assert result["kept"] == "entry-a"
        assert result["removed"] == "entry-b"
        assert result["new_confidence"] == 0.8
        assert result["merged_evidence"] == [1, 2, 3, 4, 5]

        # entry-b should be deleted
        remaining = session.query(PlaybookEntry).all()
        assert len(remaining) == 1
        assert remaining[0].name == "entry-a"

    def test_keeps_higher_confidence(self, session):
        _insert(session, "entry-a", confidence=0.3, evidence="[1]")
        _insert(session, "entry-b", confidence=0.9, evidence="[2]")

        result = merge_entries(session, keep_id=1, remove_id=2)
        assert result["new_confidence"] == 0.9

    def test_deduplicates_evidence(self, session):
        _insert(session, "entry-a", evidence="[1, 2, 3]")
        _insert(session, "entry-b", evidence="[2, 3, 4]")

        result = merge_entries(session, keep_id=1, remove_id=2)
        assert result["merged_evidence"] == [1, 2, 3, 4]

    def test_missing_entry(self, session):
        _insert(session, "entry-a")
        result = merge_entries(session, keep_id=1, remove_id=999)
        assert "error" in result

    def test_empty_evidence(self, session):
        _insert(session, "entry-a", evidence="[]")
        _insert(session, "entry-b", evidence="[]")
        result = merge_entries(session, keep_id=1, remove_id=2)
        assert result["merged_evidence"] == []
