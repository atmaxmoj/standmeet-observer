"""Tests for pipeline filter: noise removal + batch window detection."""

from datetime import datetime, timezone, timedelta

from engine.domain.observation.entity import Frame
from engine.domain.observation.filter import should_keep, detect_windows


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

    def test_osascript_noise_does_not_produce_episodes(self):
        """Realistic scenario: oslog captures observer's own osascript polling every 3s.

        These should be filtered out, producing zero windows (= zero episodes).
        Without the fix, this creates a window every ~3 minutes — the root cause
        of the 'frequent episode' bug.
        """
        base = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
        # Simulate 10 minutes of osascript launch/quit every 3 seconds (200 events)
        noise_frames = []
        for i in range(200):
            ts = (base + timedelta(seconds=i * 3)).isoformat()
            pid = 10000 + i
            noise_frames.append(_frame(
                id=i * 2, source="os_event", app_name="oslog",
                text=f"[app_launch] runningboardd: Now tracking process: [anon<osascript>(501):{pid}]",
                timestamp=ts,
            ))
            noise_frames.append(_frame(
                id=i * 2 + 1, source="os_event", app_name="oslog",
                text=f"[app_quit] runningboardd: [anon<osascript>(501):{pid}] termination reported by proc_exit",
                timestamp=ts,
            ))

        # Filter then detect windows
        kept = [f for f in noise_frames if should_keep(f)]
        windows, remainder = detect_windows(kept)

        # All noise should be filtered — zero frames kept, zero windows
        assert len(kept) == 0, f"Expected 0 frames kept, got {len(kept)}"
        assert len(windows) == 0, f"Expected 0 windows, got {len(windows)}"

    def test_osascript_noise_mixed_with_real_work(self):
        """osascript noise interleaved with real user activity.

        Only real user frames should survive filtering and produce windows.
        """
        base = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
        frames = []
        fid = 0

        # 10 minutes of osascript noise every 3s
        for i in range(200):
            ts = (base + timedelta(seconds=i * 3)).isoformat()
            frames.append(_frame(
                id=fid, source="os_event", app_name="oslog",
                text=f"[app_launch] runningboardd: Now tracking process: [anon<osascript>(501):{10000+i}]",
                timestamp=ts,
            ))
            fid += 1

        # Sprinkle in real user activity (screen captures while coding)
        for i in range(5):
            ts = (base + timedelta(minutes=i * 2)).isoformat()
            frames.append(_frame(
                id=fid, source="capture", app_name="VSCode",
                text="def process_data(): return transform(input_data)",
                timestamp=ts,
            ))
            fid += 1

        frames.sort(key=lambda f: f.timestamp)
        kept = [f for f in frames if should_keep(f)]

        # Only the 5 real captures should survive
        assert all(f.source == "capture" for f in kept), "Noise frames leaked through filter"
        assert len(kept) == 5

    def test_filters_observer_process_noise(self):
        """oslog frames from observer's own processes (osascript, node, caffeinate) should be filtered."""
        noise_texts = [
            "[app_launch] runningboardd: Now tracking process: [anon<osascript>(501):11492]",
            "[app_quit] runningboardd: [anon<osascript>(501):11491] termination reported by proc_exit",
            "[app_launch] runningboardd: Now tracking process: [anon<caffeinate>(501):5678]",
            "[app_quit] runningboardd: [anon<node>(501):9999] termination reported by proc_exit",
        ]
        for text in noise_texts:
            f = _frame(source="os_event", app_name="oslog", text=text)
            assert should_keep(f) is False, f"Should filter: {text}"

    def test_keeps_real_app_oslog_events(self):
        """oslog frames about real user apps should be kept."""
        real_texts = [
            "[app_launch] runningboardd: Now tracking process: [app<com.apple.Safari>(501):1234]",
            "[frontmost_change] com.apple.Terminal became frontmost",
            "[app_launch] runningboardd: Now tracking process: [app<com.microsoft.VSCode>(501):5678]",
        ]
        for text in real_texts:
            f = _frame(source="os_event", app_name="oslog", text=text)
            assert should_keep(f) is True, f"Should keep: {text}"

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

    def test_filters_terminal_osascript_screen_capture(self):
        """Screen capture of Terminal showing only osascript/caffeinate noise should be filtered."""
        f = _frame(source="capture", app_name="Terminal",
                   text="wangsijie 12345 osascript -e 'tell application' wangsijie 12346 osascript wangsijie 12347 caffeinate -i")
        assert should_keep(f) is False

    def test_filters_terminal_node_automation_capture(self):
        """Screen capture of Terminal showing only node process spawning."""
        f = _frame(source="capture", app_name="Terminal",
                   text="node /Users/wangsijie/.observer/sources/builtin/chrome/src/chrome_source.py 3456 node 3457 osascript")
        assert should_keep(f) is False

    def test_keeps_terminal_with_real_commands(self):
        """Terminal showing actual user commands should be kept."""
        f = _frame(source="capture", app_name="Terminal",
                   text="$ npm test tests/e2e/content/faq-block.spec.ts --grep IFAQ2b\nPASSED 5 tests")
        assert should_keep(f) is True

    def test_keeps_vscode_with_osascript_in_text(self):
        """VSCode showing code that mentions osascript should be kept."""
        f = _frame(source="capture", app_name="Code",
                   text="def run_osascript(cmd): subprocess.run(['osascript', '-e', cmd])")
        assert should_keep(f) is True

    def test_filters_chrome_showing_osascript_output(self):
        """Chrome showing terminal output with osascript noise should also be filtered."""
        f = _frame(source="capture", app_name="Google Chrome",
                   text="Process 12345 osascript -e tell application Process 12346 osascript Process 12347 caffeinate -i pid 999 osascript")
        assert should_keep(f) is False
