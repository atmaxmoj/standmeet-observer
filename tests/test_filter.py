"""Tests for pipeline filter: noise removal + window accumulation."""

from datetime import datetime, timezone, timedelta

from engine.pipeline.collector import Frame
from engine.pipeline.filter import should_keep, WindowAccumulator, IGNORE_APPS


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


class TestWindowAccumulator:
    def test_single_frame_stays_in_buffer(self):
        acc = WindowAccumulator(window_minutes=30)
        completed = acc.feed([_frame()])
        assert completed == []

    def test_flush_emits_buffer(self):
        acc = WindowAccumulator(window_minutes=30)
        acc.feed([_frame()])
        result = acc.flush()
        assert len(result) == 1

    def test_flush_empty_returns_none(self):
        acc = WindowAccumulator(window_minutes=30)
        assert acc.flush() is None

    def test_window_closes_on_time_exceeded(self):
        acc = WindowAccumulator(window_minutes=5)
        t0 = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)

        frames = []
        for i in range(10):
            t = t0 + timedelta(minutes=i)
            frames.append(_frame(id=i, timestamp=t.isoformat()))

        completed = acc.feed(frames)
        # 10 frames over 9 minutes with 5-min window → should emit at least one window
        assert len(completed) >= 1

    def test_idle_gap_triggers_flush(self):
        acc = WindowAccumulator(window_minutes=30, idle_threshold_seconds=60)
        t0 = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=30)
        t2 = t0 + timedelta(minutes=5)  # 5 min gap > 60s threshold

        frames = [
            _frame(id=1, timestamp=t0.isoformat()),
            _frame(id=2, timestamp=t1.isoformat()),
            _frame(id=3, timestamp=t2.isoformat()),
        ]

        completed = acc.feed(frames)
        assert len(completed) == 1
        # First two frames emitted as a window
        assert len(completed[0]) == 2
        # Third frame should be in buffer
        remaining = acc.flush()
        assert len(remaining) == 1
        assert remaining[0].id == 3

    def test_noise_filtered_before_accumulation(self):
        acc = WindowAccumulator(window_minutes=30)
        frames = [
            _frame(id=1, app_name="Finder", text="noise"),  # filtered
            _frame(id=2, app_name="VSCode", text="real content here"),  # kept
        ]
        acc.feed(frames)
        result = acc.flush()
        assert len(result) == 1
        assert result[0].id == 2

    def test_multiple_windows_emitted(self):
        acc = WindowAccumulator(window_minutes=2, idle_threshold_seconds=300)
        t0 = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)

        frames = []
        for i in range(10):
            t = t0 + timedelta(minutes=i)
            frames.append(_frame(id=i, timestamp=t.isoformat()))

        completed = acc.feed(frames)
        # Over 9 minutes with 2-min windows → should emit multiple windows
        # Window closes when span > 2 min, so ~4 frames per window → 2 windows emitted
        # (remaining frames stay in buffer)
        assert len(completed) >= 2
