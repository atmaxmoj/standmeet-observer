"""Tests for ZshSource — the zsh shell history collector.

These tests exposed a critical bug: on macOS, ZshSource watched .historynew
files which are ALWAYS empty during active sessions. macOS zsh session management
(/etc/zshrc_Apple_Terminal) sets HISTFILE to .historynew but only flushes
commands to it on session exit (zshexit hook). Live commands stay in memory.
"""

import os
from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path):
    """Create a fake home directory with zsh session structure."""
    return tmp_path


@pytest.fixture
def zsh_source_cls():
    """Import ZshSource (requires zsh source plugin venv)."""
    try:
        from zsh_source import ZshSource
        return ZshSource
    except ImportError:
        pytest.skip("zsh_source not importable (run from source venv)")


class TestHistoryFileTracker:
    """Unit tests for _HistoryFileTracker."""

    @pytest.fixture
    def make_tracker(self):
        try:
            from zsh_source import _HistoryFileTracker, _parse_zsh_line
            return lambda path: _HistoryFileTracker(path, parser=_parse_zsh_line)
        except ImportError:
            pytest.skip("zsh_source not importable")

    def test_empty_file_returns_nothing(self, tmp_path, make_tracker):
        """An empty file should return no commands."""
        f = tmp_path / "test.history"
        f.write_text("")
        tracker = make_tracker(f)
        assert tracker.collect_new() == []

    def test_first_read_establishes_baseline(self, tmp_path, make_tracker):
        """First read should set baseline, not return existing lines."""
        f = tmp_path / "test.history"
        f.write_text(": 1711929600:0;echo hello\n: 1711929601:0;echo world\n")
        tracker = make_tracker(f)
        assert tracker.collect_new() == []

    def test_new_lines_returned_after_baseline(self, tmp_path, make_tracker):
        """Lines added after baseline should be returned."""
        f = tmp_path / "test.history"
        f.write_text(": 1711929600:0;echo hello\n")
        tracker = make_tracker(f)
        tracker.collect_new()  # baseline

        with open(f, "a") as fh:
            fh.write(": 1711929602:0;git status\n")

        new = tracker.collect_new()
        assert len(new) == 1
        assert "git status" in new[0]

    def test_noise_filtered(self, tmp_path, make_tracker):
        """Trivial commands (ls, cd, etc.) should be filtered."""
        f = tmp_path / "test.history"
        f.write_text(": 1711929600:0;echo baseline\n")
        tracker = make_tracker(f)
        tracker.collect_new()  # baseline

        with open(f, "a") as fh:
            fh.write(": 1711929601:0;ls\n")
            fh.write(": 1711929602:0;cd projects\n")
            fh.write(": 1711929603:0;npx vercel --prod\n")

        new = tracker.collect_new()
        assert len(new) == 1
        assert "vercel" in new[0]

    def test_missing_file_returns_nothing(self, tmp_path, make_tracker):
        """Non-existent file should not crash."""
        tracker = make_tracker(tmp_path / "nonexistent.history")
        assert tracker.collect_new() == []


class TestZshSourceSessionMode:
    """Tests for macOS session mode (.zsh_sessions/)."""

    def test_probe_finds_session_files(self, home, zsh_source_cls):
        """Probe should find .historynew files in session mode."""
        sessions = home / ".zsh_sessions"
        sessions.mkdir()
        (sessions / "ABC123.historynew").write_text("")
        (sessions / "DEF456.historynew").write_text("")

        source = zsh_source_cls(home=home)
        result = source.probe()
        assert result.available
        assert "session mode" in result.description
        assert len(result.paths) == 2

    def test_empty_historynew_returns_no_commands(self, home, zsh_source_cls):
        """CRITICAL: .historynew files are ALWAYS empty on macOS during active
        sessions. This test documents the bug — collect() returns nothing."""
        sessions = home / ".zsh_sessions"
        sessions.mkdir()
        (sessions / "ABC123.historynew").write_text("")

        source = zsh_source_cls(home=home)
        source.probe()

        # Simulate multiple collect cycles — all return empty
        for _ in range(5):
            records = source.collect()
            assert records == [], "Empty .historynew should produce no records"

    def test_history_file_has_data_but_not_watched(self, home, zsh_source_cls):
        """CRITICAL: .history files have real commands but ZshSource ignores them.
        This test documents the gap — real data exists in .history, not .historynew."""
        sessions = home / ".zsh_sessions"
        sessions.mkdir()

        # .historynew = empty (macOS default during active session)
        (sessions / "ABC123.historynew").write_text("")

        # .history = real data (written on session close)
        (sessions / "ABC123.history").write_text(
            ": 1711929600:0;npx vercel --prod\n"
            ": 1711929601:0;docker compose up -d\n"
            ": 1711929602:0;git push origin main\n"
        )

        source = zsh_source_cls(home=home)
        result = source.probe()

        # Probe finds .historynew but NOT .history
        assert all(".historynew" in p for p in result.paths)

        # Collect returns nothing because .historynew is empty
        records = source.collect()
        assert records == []

        # But 3 real commands exist in .history that we're missing!
        history_file = sessions / "ABC123.history"
        assert history_file.read_text().count("\n") == 3

    def test_probe_skips_zsh_history_in_session_mode(self, home, zsh_source_cls):
        """In session mode, ~/.zsh_history should be skipped."""
        sessions = home / ".zsh_sessions"
        sessions.mkdir()
        (sessions / "ABC123.historynew").write_text("")
        (home / ".zsh_history").write_text(": 1711929600:0;echo hello\n")

        source = zsh_source_cls(home=home)
        result = source.probe()
        assert any("skipped" in w for w in result.warnings)


class TestZshSourceStandardMode:
    """Tests for non-session mode (no .zsh_sessions/ dir)."""

    def test_probe_finds_zsh_history(self, home, zsh_source_cls):
        """Without sessions dir, should use ~/.zsh_history."""
        (home / ".zsh_history").write_text(": 1711929600:0;echo hello\n")

        source = zsh_source_cls(home=home)
        result = source.probe()
        assert result.available
        assert "standard" in result.description

    def test_collect_returns_new_commands(self, home, zsh_source_cls):
        """New commands appended to .zsh_history should be collected."""
        hist = home / ".zsh_history"
        hist.write_text(": 1711929600:0;echo baseline\n")

        source = zsh_source_cls(home=home)
        source.collect()  # baseline

        with open(hist, "a") as f:
            f.write(": 1711929601:0;npm test\n")

        records = source.collect()
        assert len(records) == 1
        assert "npm test" in records[0]["command"]

    def test_probe_no_history_at_all(self, home, zsh_source_cls):
        """No history file = not available."""
        source = zsh_source_cls(home=home)
        result = source.probe()
        assert not result.available


class TestParseZshLine:
    """Tests for the zsh history line parser."""

    @pytest.fixture
    def parse(self):
        try:
            from zsh_source import _parse_zsh_line
            return _parse_zsh_line
        except ImportError:
            pytest.skip("zsh_source not importable")

    def test_extended_format(self, parse):
        assert parse(": 1711929600:0;echo hello") == "echo hello"

    def test_plain_format(self, parse):
        assert parse("echo hello") == "echo hello"

    def test_empty_line(self, parse):
        assert parse("") == ""
        assert parse("  ") == ""

    def test_extended_with_semicolons(self, parse):
        """Commands containing semicolons should be preserved."""
        assert parse(": 1711929600:0;echo a; echo b") == "echo a; echo b"
