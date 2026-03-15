"""Tests for pipeline filter: noise removal + batch window detection."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from engine.pipeline.collector import Frame
from engine.pipeline.filter import should_keep, detect_windows, IGNORE_APPS


def _frame(
    id=1, source="capture", app_name="VSCode", text="some meaningful text here",
    timestamp="2026-03-14T10:00:00+00:00", window_name="editor", image_path="",
) -> Frame:
    return Frame(
        id=id, source=source, app_name=app_name, text=text,
        timestamp=timestamp, window_name=window_name, image_path=image_path,
    )


class TestShouldKeep:
    def test_keeps_normal_frame(self):
        assert should_keep(_frame()) is True

    def test_filters_ignored_apps(self):
        for app in ["Finder", "Dock", "Spotlight", "loginwindow"]:
            assert should_keep(_frame(app_name=app)) is False

    def test_filters_short_text(self):
        assert should_keep(_frame(text="hi")) is False
        assert should_keep(_frame(text="")) is False
        assert should_keep(_frame(text="   ")) is False

    def test_keeps_text_at_threshold(self):
        assert should_keep(_frame(text="a" * 10)) is True

    def test_audio_passes_through(self):
        f = _frame(source="audio", app_name="microphone", text="hello world")
        assert should_keep(f) is True

    def test_audio_empty_text_filtered(self):
        f = _frame(source="audio", app_name="microphone", text="")
        assert should_keep(f) is False
        f2 = _frame(source="audio", app_name="microphone", text="   ")
        assert should_keep(f2) is False

    def test_os_event_passes_through(self):
        f = _frame(source="os_event", app_name="shell_command", text="git push origin main")
        assert should_keep(f) is True

    def test_os_event_empty_data_filtered(self):
        f = _frame(source="os_event", app_name="shell_command", text="")
        assert should_keep(f) is False
        f2 = _frame(source="os_event", app_name="browser_url", text="   ")
        assert should_keep(f2) is False

    def test_os_event_not_affected_by_ignore_apps(self):
        """os_events use event_type as app_name, should never be filtered by IGNORE_APPS."""
        f = _frame(source="os_event", app_name="Finder", text="some event data here")
        assert should_keep(f) is True


class TestDetectWindows:
    def test_empty_input(self):
        windows, remainder = detect_windows([])
        assert windows == []
        assert remainder == []

    def test_single_frame_stays_as_remainder(self):
        """A single recent frame should stay in remainder (not yet a complete window)."""
        now = datetime.now(timezone.utc)
        f = _frame(timestamp=now.isoformat())
        windows, remainder = detect_windows([f])
        assert windows == []
        assert len(remainder) == 1

    def test_old_frames_emitted(self):
        """Frames older than idle_seconds from now should be emitted."""
        old = datetime.now(timezone.utc) - timedelta(minutes=30)
        frames = [
            _frame(id=1, timestamp=old.isoformat()),
            _frame(id=2, timestamp=(old + timedelta(seconds=10)).isoformat()),
        ]
        windows, remainder = detect_windows(frames, idle_seconds=60)
        assert len(windows) == 1
        assert len(windows[0]) == 2
        assert remainder == []

    def test_idle_gap_splits_window(self):
        """A gap > idle_seconds between frames splits into separate windows."""
        t0 = datetime.now(timezone.utc) - timedelta(hours=1)
        frames = [
            _frame(id=1, timestamp=t0.isoformat()),
            _frame(id=2, timestamp=(t0 + timedelta(seconds=10)).isoformat()),
            # 10 minute gap
            _frame(id=3, timestamp=(t0 + timedelta(minutes=10)).isoformat()),
            _frame(id=4, timestamp=(t0 + timedelta(minutes=10, seconds=5)).isoformat()),
        ]
        windows, remainder = detect_windows(frames, idle_seconds=60)
        # First group [1,2] emitted (idle gap before frame 3)
        # Second group [3,4] — depends on whether it's old enough from "now"
        assert len(windows) >= 1
        assert len(windows[0]) == 2

    def test_time_span_splits_window(self):
        """Window closes when span exceeds window_minutes."""
        t0 = datetime.now(timezone.utc) - timedelta(hours=2)
        frames = []
        for i in range(10):
            t = t0 + timedelta(minutes=i)
            frames.append(_frame(id=i, timestamp=t.isoformat()))

        windows, remainder = detect_windows(frames, window_minutes=5, idle_seconds=300)
        # 10 frames over 9 min with 5-min window → at least 1 complete window
        assert len(windows) >= 1

    def test_multiple_windows(self):
        """Multiple windows emitted when frames span long time."""
        t0 = datetime.now(timezone.utc) - timedelta(hours=3)
        frames = []
        for i in range(20):
            t = t0 + timedelta(minutes=i * 2)  # 2 min apart, 38 min total
            frames.append(_frame(id=i, timestamp=t.isoformat()))

        windows, remainder = detect_windows(frames, window_minutes=10, idle_seconds=300)
        # 38 minutes / 10-min windows → at least 3 windows
        assert len(windows) >= 3

    def test_recent_frames_stay_as_remainder(self):
        """Frames from the last few seconds should stay as remainder."""
        now = datetime.now(timezone.utc)
        frames = [
            _frame(id=1, timestamp=(now - timedelta(seconds=10)).isoformat()),
            _frame(id=2, timestamp=(now - timedelta(seconds=5)).isoformat()),
            _frame(id=3, timestamp=now.isoformat()),
        ]
        windows, remainder = detect_windows(frames, idle_seconds=60)
        assert windows == []
        assert len(remainder) == 3

    def test_mixed_old_and_recent(self):
        """Old frames emitted as window, recent frames stay as remainder."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=1)
        frames = [
            _frame(id=1, timestamp=old.isoformat()),
            _frame(id=2, timestamp=(old + timedelta(seconds=10)).isoformat()),
            # 50 min gap → idle split
            _frame(id=3, timestamp=(now - timedelta(seconds=5)).isoformat()),
        ]
        windows, remainder = detect_windows(frames, idle_seconds=60)
        assert len(windows) == 1
        assert len(windows[0]) == 2
        assert len(remainder) == 1
        assert remainder[0].id == 3
