"""Tests for ZshSource — the zsh shell history collector.

Tests run against real zsh processes and real macOS session files,
not hand-crafted fake data.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture
def zsh_source_cls():
    try:
        from zsh_source import ZshSource
        return ZshSource
    except ImportError:
        pytest.skip("zsh_source not importable")


@pytest.fixture
def parse_fn():
    try:
        from zsh_source import _parse_zsh_line
        return _parse_zsh_line
    except ImportError:
        pytest.skip("zsh_source not importable")


@pytest.fixture
def tracker_cls():
    try:
        from zsh_source import _HistoryFileTracker, _parse_zsh_line
        return lambda path: _HistoryFileTracker(path, parser=_parse_zsh_line)
    except ImportError:
        pytest.skip("zsh_source not importable")


class TestRealZshSession:
    """Tests against a real zsh process — the actual scenario that's broken."""

    def test_collect_commands_from_live_zsh(self, zsh_source_cls):
        """Spawn a real zsh, run commands, verify ZshSource captures them.
        This is the core test — it fails because macOS zsh keeps
        commands in memory and doesn't flush to .historynew."""
        home = Path.home()
        source = zsh_source_cls(home=home)
        result = source.probe()
        if not result.available:
            pytest.skip("No zsh history available on this machine")

        # Baseline
        source.collect()

        # Run a real command in a new zsh subprocess with unique marker
        marker = f"observer_test_{int(time.time())}"
        subprocess.run(
            ["zsh", "-i", "-c", f"echo {marker}"],
            capture_output=True, timeout=5,
            env={**os.environ, "TERM_SESSION_ID": ""},  # disable session mode in child
        )
        time.sleep(1)

        records = source.collect()
        commands = [r["command"] for r in records]
        assert any(marker in cmd for cmd in commands), (
            f"ZshSource did not capture command with marker '{marker}'. "
            f"Got {len(records)} records: {commands[:5]}"
        )

    def test_collect_from_real_history_files(self, zsh_source_cls):
        """On this machine, verify that ZshSource can read from whatever
        history files actually exist and have data."""
        home = Path.home()
        sessions = home / ".zsh_sessions"

        if sessions.is_dir():
            # macOS session mode — check if .history files have data
            history_files = list(sessions.glob("*.history"))
            total_lines = sum(
                len(f.read_text(errors="replace").splitlines())
                for f in history_files if f.stat().st_size > 0
            )
            assert total_lines > 0, (
                f"Found {len(history_files)} .history files but they're all empty. "
                "ZshSource should be watching these."
            )

            # Now check what ZshSource actually watches
            source = zsh_source_cls(home=home)
            result = source.probe()
            watched_paths = result.paths

            # BUG: ZshSource watches .historynew (empty) not .history (has data)
            has_history_in_paths = any(".history" in p and ".historynew" not in p for p in watched_paths)
            assert has_history_in_paths, (
                f"ZshSource watches {watched_paths} but real data is in .history files. "
                f"Found {total_lines} lines across {len(history_files)} .history files."
            )
        else:
            # Standard mode — ~/.zsh_history should be watched
            hist = home / ".zsh_history"
            if not hist.exists():
                pytest.skip("No .zsh_history on this machine")
            source = zsh_source_cls(home=home)
            result = source.probe()
            assert any(".zsh_history" in p for p in result.paths)


class TestParseZshLine:
    """Parser must handle real macOS zsh history format."""

    def test_real_history_format(self, parse_fn):
        """Parse lines from actual ~/.zsh_history."""
        hist = Path.home() / ".zsh_history"
        if not hist.exists() or hist.stat().st_size == 0:
            pytest.skip("No .zsh_history on this machine")

        lines = hist.read_text(errors="replace").splitlines()[:20]
        parsed = [parse_fn(line) for line in lines if line.strip()]
        non_empty = [p for p in parsed if p]

        assert len(non_empty) > 0, (
            f"Parser returned nothing for {len(lines)} real history lines. "
            f"Sample lines: {lines[:3]}"
        )

    def test_extended_format(self, parse_fn):
        assert parse_fn(": 1711929600:0;echo hello") == "echo hello"

    def test_extended_with_semicolons(self, parse_fn):
        assert parse_fn(": 1711929600:0;echo a; echo b") == "echo a; echo b"

    def test_plain_format(self, parse_fn):
        assert parse_fn("echo hello") == "echo hello"

    def test_empty(self, parse_fn):
        assert parse_fn("") == ""


class TestHistoryFileTracker:
    """Tracker must detect new lines appended to history files."""

    def test_detects_appended_lines(self, tmp_path, tracker_cls):
        f = tmp_path / "test.history"
        f.write_text(": 1711929600:0;echo baseline\n")
        tracker = tracker_cls(f)
        tracker.collect_new()  # baseline

        with open(f, "a") as fh:
            fh.write(": 1711929601:0;git status\n")

        new = tracker.collect_new()
        assert len(new) == 1
        assert "git status" in new[0]

    def test_filters_noise(self, tmp_path, tracker_cls):
        f = tmp_path / "test.history"
        f.write_text(": 1711929600:0;echo baseline\n")
        tracker = tracker_cls(f)
        tracker.collect_new()

        with open(f, "a") as fh:
            fh.write(": 1711929601:0;ls\n")
            fh.write(": 1711929602:0;cd projects\n")
            fh.write(": 1711929603:0;npx vercel --prod\n")

        new = tracker.collect_new()
        assert len(new) == 1
        assert "vercel" in new[0]

    def test_missing_file(self, tmp_path, tracker_cls):
        tracker = tracker_cls(tmp_path / "nope.history")
        assert tracker.collect_new() == []
