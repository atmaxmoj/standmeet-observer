"""Tests for raw capture data recall tools."""

import pytest
from engine.infrastructure.persistence.models import Frame, AudioFrame, OsEvent
from engine.infrastructure.agent.repository import (
    get_recent_frames,
    get_frames_by_app,
    get_recent_audio,
    get_recent_os_events,
    get_os_events_by_type,
)


@pytest.fixture
def session(sync_session):
    return sync_session


class TestGetRecentFrames:
    def test_empty(self, session):
        assert get_recent_frames(session, hours=24) == []

    def test_returns_recent(self, session):
        session.add(Frame(timestamp="2026-03-16T10:00:00Z", app_name="VSCode", window_name="main.py", text="def hello():"))
        session.commit()
        results = get_recent_frames(session, hours=24)
        assert len(results) == 1
        assert results[0]["app_name"] == "VSCode"

    def test_excludes_old(self, session):
        session.add(Frame(timestamp="t1", app_name="VSCode", text="old", created_at="2020-01-01T00:00:00Z"))
        session.add(Frame(timestamp="t2", app_name="Chrome", text="new"))
        session.commit()
        results = get_recent_frames(session, hours=24)
        assert len(results) == 1
        assert results[0]["app_name"] == "Chrome"

    def test_limit(self, session):
        for i in range(20):
            session.add(Frame(timestamp=f"t{i}", app_name="app", text=f"text {i}"))
        session.commit()
        results = get_recent_frames(session, hours=24, limit=5)
        assert len(results) == 5

    def test_truncates_text(self, session):
        long_text = "x" * 1000
        session.add(Frame(timestamp="t1", app_name="app", text=long_text))
        session.commit()
        results = get_recent_frames(session, hours=24)
        assert len(results[0]["text"]) <= 300


class TestGetFramesByApp:
    def test_empty(self, session):
        assert get_frames_by_app(session, "VSCode") == []

    def test_filters(self, session):
        session.add(Frame(timestamp="t1", app_name="VSCode", text="code"))
        session.add(Frame(timestamp="t2", app_name="Chrome", text="browse"))
        session.commit()
        results = get_frames_by_app(session, "VSCode")
        assert len(results) == 1
        assert results[0]["text"] == "code"

    def test_partial_match(self, session):
        session.add(Frame(timestamp="t1", app_name="Visual Studio Code", text="code"))
        session.commit()
        results = get_frames_by_app(session, "Visual Studio")
        assert len(results) == 1


class TestGetRecentAudio:
    def test_empty(self, session):
        assert get_recent_audio(session, hours=24) == []

    def test_returns_recent(self, session):
        session.add(AudioFrame(timestamp="t1", text="hello world", language="en", duration_seconds=5.0))
        session.commit()
        results = get_recent_audio(session, hours=24)
        assert len(results) == 1
        assert results[0]["text"] == "hello world"
        assert results[0]["language"] == "en"

    def test_excludes_old(self, session):
        session.add(AudioFrame(timestamp="t1", text="old", created_at="2020-01-01T00:00:00Z"))
        session.add(AudioFrame(timestamp="t2", text="new"))
        session.commit()
        results = get_recent_audio(session, hours=24)
        assert len(results) == 1
        assert results[0]["text"] == "new"


class TestGetRecentOsEvents:
    def test_empty(self, session):
        assert get_recent_os_events(session, hours=24) == []

    def test_returns_recent(self, session):
        session.add(OsEvent(timestamp="t1", event_type="shell", source="zsh", data="git status"))
        session.commit()
        results = get_recent_os_events(session, hours=24)
        assert len(results) == 1
        assert results[0]["data"] == "git status"

    def test_excludes_old(self, session):
        session.add(OsEvent(timestamp="t1", event_type="shell", data="old cmd", created_at="2020-01-01T00:00:00Z"))
        session.add(OsEvent(timestamp="t2", event_type="url", data="new url"))
        session.commit()
        results = get_recent_os_events(session, hours=24)
        assert len(results) == 1


class TestGetOsEventsByType:
    def test_empty(self, session):
        assert get_os_events_by_type(session, "shell") == []

    def test_filters(self, session):
        session.add(OsEvent(timestamp="t1", event_type="shell", data="git status"))
        session.add(OsEvent(timestamp="t2", event_type="url", data="https://github.com"))
        session.commit()
        results = get_os_events_by_type(session, "shell")
        assert len(results) == 1
        assert results[0]["data"] == "git status"

    def test_limit(self, session):
        for i in range(30):
            session.add(OsEvent(timestamp=f"t{i}", event_type="shell", data=f"cmd {i}"))
        session.commit()
        results = get_os_events_by_type(session, "shell", limit=10)
        assert len(results) == 10
