"""Tests for episode recall tools."""

import pytest
from engine.infrastructure.persistence.models import Episode
from engine.infrastructure.agent.repository import search_episodes, get_recent_episodes, get_episodes_by_app


@pytest.fixture
def session(sync_session):
    return sync_session


def _insert_episode(session, summary, app_names="[]", started_at="2026-03-15T10:00:00Z",
                     ended_at="2026-03-15T10:30:00Z", created_at=None):
    kwargs = dict(summary=summary, app_names=app_names, started_at=started_at, ended_at=ended_at)
    if created_at:
        kwargs["created_at"] = created_at
    session.add(Episode(**kwargs))
    session.commit()


class TestSearchEpisodes:
    def test_empty_db(self, session):
        assert search_episodes(session, "coding") == []

    def test_finds_matching(self, session):
        _insert_episode(session, "Writing Python code in VSCode")
        _insert_episode(session, "Browsing Reddit in Chrome")
        results = search_episodes(session, "Python")
        assert len(results) == 1
        assert "Python" in results[0]["summary"]

    def test_case_sensitive_like(self, session):
        _insert_episode(session, "Writing Python code")
        # PostgreSQL LIKE is case-sensitive
        results = search_episodes(session, "Python")
        assert len(results) == 1
        results = search_episodes(session, "python")
        assert len(results) == 0

    def test_limit(self, session):
        for i in range(10):
            _insert_episode(session, f"coding session {i}")
        results = search_episodes(session, "coding", limit=3)
        assert len(results) == 3

    def test_no_match(self, session):
        _insert_episode(session, "Writing Python code")
        assert search_episodes(session, "golang") == []


class TestGetRecentEpisodes:
    def test_empty_db(self, session):
        assert get_recent_episodes(session, hours=24) == []

    def test_recent_episodes_returned(self, session):
        _insert_episode(session, "Recent work")
        results = get_recent_episodes(session, hours=24)
        assert len(results) == 1

    def test_old_episodes_excluded(self, session):
        _insert_episode(session, "Old work", created_at="2020-01-01T00:00:00Z")
        _insert_episode(session, "Recent work")
        results = get_recent_episodes(session, hours=24)
        assert len(results) == 1
        assert results[0]["summary"] == "Recent work"


class TestGetEpisodesByApp:
    def test_empty_db(self, session):
        assert get_episodes_by_app(session, "VSCode") == []

    def test_filters_by_app(self, session):
        _insert_episode(session, "Coding", app_names='["VSCode"]')
        _insert_episode(session, "Browsing", app_names='["Chrome"]')
        results = get_episodes_by_app(session, "VSCode")
        assert len(results) == 1
        assert results[0]["summary"] == "Coding"

    def test_partial_match(self, session):
        _insert_episode(session, "Coding", app_names='["Visual Studio Code"]')
        results = get_episodes_by_app(session, "Visual Studio")
        assert len(results) == 1
