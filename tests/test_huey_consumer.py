"""Tests for Huey consumer embedded mode + backfill logic.

These tests verify:
1. EmbeddedConsumer actually starts without crashing (catches method name bugs)
2. Backfill produces reasonable window counts from historical data
"""

import threading
import time
from datetime import datetime, timezone, timedelta


from engine.etl.entities import Frame
from engine.etl.filter import should_keep, detect_windows


class TestEmbeddedConsumer:
    def test_consumer_thread_stays_alive(self, tmp_path, monkeypatch):
        """EmbeddedConsumer must not crash on startup.

        Regression: _install_signal_handlers vs _set_signal_handlers mismatch
        caused the consumer thread to die immediately with an exception.
        """
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-test-key")
        monkeypatch.setenv("DATABASE_URL_SYNC", f"sqlite:///{tmp_path}/test.db")
        monkeypatch.setenv("HUEY_DB_DIR", str(tmp_path))

        from huey import SqliteHuey
        from engine.main import _start_huey_consumer

        # Patch engine.scheduler.tasks.huey to use a temp DB
        import engine.scheduler.tasks as tasks_mod
        original_huey = tasks_mod.huey
        test_huey = SqliteHuey(filename=str(tmp_path / "huey_test.db"))
        monkeypatch.setattr(tasks_mod, "huey", test_huey)

        try:
            consumer = _start_huey_consumer()

            # Give it a moment to start up (or crash)
            time.sleep(0.5)

            # Find the huey thread
            huey_thread = None
            for t in threading.enumerate():
                if t.name == "huey":
                    huey_thread = t
                    break

            assert huey_thread is not None, "Huey thread not found"
            assert huey_thread.is_alive(), (
                "Huey consumer thread died — likely _set_signal_handlers "
                "method name mismatch (was _install_signal_handlers)"
            )

            # Clean up
            consumer.stop()
            huey_thread.join(timeout=3)
        finally:
            monkeypatch.setattr(tasks_mod, "huey", original_huey)

    def test_wrong_method_name_crashes(self, tmp_path):
        """Verify that the WRONG method name does cause a crash.

        This proves the test above actually catches the bug.
        """
        from huey.consumer import Consumer
        from huey import SqliteHuey

        test_huey = SqliteHuey(filename=str(tmp_path / "test2.db"))

        class BrokenConsumer(Consumer):
            def _install_signal_handlers(self):
                pass  # Wrong method name!

        consumer = BrokenConsumer(test_huey, workers=1, periodic=False)
        thread = threading.Thread(target=consumer.run, daemon=True, name="test-huey-broken")
        thread.start()

        time.sleep(0.5)

        # This thread should be dead — proving the wrong name causes crash
        assert not thread.is_alive(), (
            "Consumer with wrong method name should have crashed"
        )


class TestBackfillWindowCount:
    """Verify backfill produces reasonable window counts, not one-per-frame."""

    def _make_frames(self, groups):
        """Create frames from group specs: [(count, minutes_ago, gap_minutes), ...]

        Each group is a cluster of frames. gap_minutes is the gap BEFORE this group.
        """
        frames = []
        fid = 1
        for count, minutes_ago, _ in groups:
            base = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
            for i in range(count):
                t = (base + timedelta(seconds=i * 5)).isoformat()  # 5s between frames
                frames.append(Frame(
                    id=fid, source="capture",
                    text=f"meaningful content line {fid} here for testing",
                    app_name="VSCode", window_name="editor.py",
                    timestamp=t,
                ))
                fid += 1
        return sorted(frames, key=lambda f: f.timestamp)

    def test_continuous_session_one_window(self):
        """Frames with no idle gaps → 1 window (not N windows)."""
        # 20 frames over ~100 seconds, all old enough
        frames = self._make_frames([(20, 60, 0)])
        kept = [f for f in frames if should_keep(f)]

        windows, remainder = detect_windows(kept, window_minutes=30, idle_seconds=300)
        if remainder:
            windows.append(remainder)

        assert len(windows) == 1, f"Expected 1 window, got {len(windows)}"
        assert len(windows[0]) == 20

    def test_two_sessions_two_windows(self):
        """Two clusters separated by >5min idle → 2 windows."""
        frames = self._make_frames([
            (10, 120, 0),   # Group 1: 2 hours ago
            (10, 30, 0),    # Group 2: 30 min ago (90 min gap from group 1)
        ])
        kept = [f for f in frames if should_keep(f)]

        windows, remainder = detect_windows(kept, window_minutes=30, idle_seconds=300)
        if remainder:
            windows.append(remainder)

        assert len(windows) == 2, f"Expected 2 windows, got {len(windows)}"

    def test_many_frames_reasonable_windows(self):
        """2000 frames over 2 hours with a few idle gaps → reasonable window count."""
        # Simulate: 500 frames over 40min, 5min gap, 500 frames, 5min gap, 500, 5min gap, 500
        frames = []
        fid = 1
        base = datetime.now(timezone.utc) - timedelta(hours=3)
        t = base
        for group in range(4):
            for i in range(500):
                frames.append(Frame(
                    id=fid, source="capture",
                    text=f"code content for testing frame {fid}",
                    app_name="VSCode", window_name="main.py",
                    timestamp=t.isoformat(),
                ))
                fid += 1
                t += timedelta(seconds=5)
            t += timedelta(minutes=10)  # 10 min idle gap between groups

        kept = [f for f in frames if should_keep(f)]
        windows, remainder = detect_windows(kept, window_minutes=30, idle_seconds=300)
        if remainder:
            windows.append(remainder)

        # 4 groups with 10min gaps → should be ~4 windows (maybe more if 30min span cuts)
        # Each group is 500*5s = 2500s ≈ 41min, so each gets cut by window_minutes=30
        # Expect roughly 4-8 windows, NOT 2000
        assert len(windows) < 20, f"Too many windows ({len(windows)}) — likely splitting per-frame"
        assert len(windows) >= 4, f"Too few windows ({len(windows)})"

    def test_idle_seconds_zero_creates_too_many(self):
        """Prove that idle_seconds=0 creates far too many windows (the bug)."""
        frames = self._make_frames([(50, 60, 0)])
        kept = [f for f in frames if should_keep(f)]

        # With idle_seconds=0, every gap > 0 seconds splits
        windows, _ = detect_windows(kept, window_minutes=30, idle_seconds=0)

        # This should create way too many windows (nearly one per frame)
        assert len(windows) > 10, (
            f"idle_seconds=0 should over-split, got {len(windows)} windows"
        )
