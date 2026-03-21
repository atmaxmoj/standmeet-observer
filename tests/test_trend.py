"""Tests for playbook trend query tools."""

import pytest
from engine.infrastructure.persistence.models import PlaybookEntry, PlaybookHistory
from engine.infrastructure.agent.repository import get_playbook_history, get_stale_entries, get_similar_entries


@pytest.fixture
def session(sync_session):
    return sync_session


def _insert_playbook(session, name, confidence=0.5, maturity="nascent", evidence="[]",
                      last_evidence_at=None, context=""):
    session.add(PlaybookEntry(
        name=name, context=context, confidence=confidence,
        maturity=maturity, evidence=evidence, last_evidence_at=last_evidence_at,
    ))
    session.commit()


def _insert_history(session, name, confidence, maturity="nascent", evidence="[]",
                     change_reason="", created_at=None):
    kwargs = dict(
        playbook_name=name, confidence=confidence, maturity=maturity,
        evidence=evidence, change_reason=change_reason,
    )
    if created_at:
        kwargs["created_at"] = created_at
    session.add(PlaybookHistory(**kwargs))
    session.commit()


class TestGetPlaybookHistory:
    def test_empty(self, session):
        assert get_playbook_history(session, "nonexistent") == []

    def test_returns_history(self, session):
        _insert_history(session, "morning-coding", 0.3, "nascent", change_reason="initial")
        _insert_history(session, "morning-coding", 0.6, "developing", change_reason="new evidence")
        history = get_playbook_history(session, "morning-coding")
        assert len(history) == 2
        assert history[0]["confidence"] == 0.3
        assert history[1]["confidence"] == 0.6

    def test_filters_by_name(self, session):
        _insert_history(session, "morning-coding", 0.5)
        _insert_history(session, "evening-browsing", 0.3)
        assert len(get_playbook_history(session, "morning-coding")) == 1


class TestGetStaleEntries:
    def test_empty_db(self, session):
        assert get_stale_entries(session, days=14) == []

    def test_no_evidence_date_is_stale(self, session):
        _insert_playbook(session, "old-pattern", last_evidence_at=None)
        results = get_stale_entries(session, days=14)
        assert len(results) == 1
        assert results[0]["name"] == "old-pattern"

    def test_recent_evidence_not_stale(self, session):
        _insert_playbook(session, "fresh-pattern", last_evidence_at="2099-01-01T00:00:00Z")
        results = get_stale_entries(session, days=14)
        assert len(results) == 0

    def test_old_evidence_is_stale(self, session):
        _insert_playbook(session, "old-pattern", last_evidence_at="2020-01-01T00:00:00Z")
        results = get_stale_entries(session, days=14)
        assert len(results) == 1


class TestGetSimilarEntries:
    def test_empty_db(self, session):
        assert get_similar_entries(session, "morning-coding") == []

    def test_finds_similar_names(self, session):
        _insert_playbook(session, "morning-coding")
        _insert_playbook(session, "afternoon-coding")
        _insert_playbook(session, "morning-browsing")
        _insert_playbook(session, "evening-gaming")

        # "morning-coding" words: {morning, coding}
        results = get_similar_entries(session, "morning-coding")
        names = [r["name"] for r in results]
        # afternoon-coding shares "coding" (similarity = 1/3 ~ 0.33)
        # morning-browsing shares "morning" (similarity = 1/3 ~ 0.33)
        assert "afternoon-coding" in names
        assert "morning-browsing" in names
        # evening-gaming shares nothing
        assert "evening-gaming" not in names

    def test_similarity_score_included(self, session):
        _insert_playbook(session, "morning-coding")
        _insert_playbook(session, "morning-coding-session")
        results = get_similar_entries(session, "morning-coding")
        assert len(results) == 1
        assert "similarity" in results[0]
        assert results[0]["similarity"] > 0.3

    def test_excludes_self(self, session):
        _insert_playbook(session, "morning-coding")
        results = get_similar_entries(session, "morning-coding")
        assert len(results) == 0
