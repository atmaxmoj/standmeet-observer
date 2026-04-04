"""Zsh shell history source plugin.

macOS zsh session management (/etc/zshrc_Apple_Terminal):
- Active session commands stay in memory, NOT written to disk
- .historynew is always empty during active sessions
- On session close: commands flush to .historynew → append to .history + ~/.zsh_history → .historynew deleted
- Therefore we watch .history files (updated on tab close) and ~/.zsh_history (shared across all sessions)
"""

import logging
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from source_framework.plugin import SourcePlugin, ProbeResult

logger = logging.getLogger(__name__)


def _signal_zsh_flush():
    """Send SIGUSR1 to running zsh processes to trigger history write.
    Note: this does NOT work on macOS default zsh (no SIGUSR1 handler).
    Kept for compatibility with custom zsh configs that support it."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "zsh"], capture_output=True, text=True, timeout=2,
        )
        pids = result.stdout.strip().split()
        my_pid = os.getpid()
        for pid_str in pids:
            pid = int(pid_str)
            if pid == my_pid:
                continue
            try:
                os.kill(pid, signal.SIGUSR1)
            except (ProcessLookupError, PermissionError):
                pass
    except Exception:
        pass


def _parse_zsh_line(line: str) -> str:
    """Parse a zsh history line. Handles both extended and plain format."""
    line = line.strip()
    if not line:
        return ""
    if line.startswith(": ") and ";" in line:
        return line.split(";", 1)[1].strip()
    return line


def _is_noise(cmd: str) -> bool:
    """Filter out noisy/trivial commands."""
    trivial = {"ls", "cd", "pwd", "clear", "exit", "history", "l", "ll", "la"}
    first_word = cmd.split()[0] if cmd.split() else ""
    return first_word in trivial


class _HistoryFileTracker:
    """Tracks a single history file for new lines."""

    def __init__(self, path: Path, parser=None):
        self.path = path
        self._parser = parser or (lambda line: line.strip())
        self._last_size = 0
        self._last_line_count = 0

    def collect_new(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            size = self.path.stat().st_size
            if size <= self._last_size:
                return []

            with open(self.path, "rb") as f:
                raw = f.read()
            lines = raw.decode("utf-8", errors="replace").splitlines()

            if self._last_line_count == 0:
                self._last_line_count = len(lines)
                self._last_size = size
                return []

            if len(lines) <= self._last_line_count:
                return []

            new_lines = lines[self._last_line_count:]
            self._last_line_count = len(lines)
            self._last_size = size

            commands = []
            for line in new_lines:
                cmd = self._parser(line)
                if cmd and not _is_noise(cmd):
                    commands.append(cmd)
            return commands
        except Exception:
            logger.exception("failed to read %s", self.path)
            return []


class ZshSource(SourcePlugin):
    """Captures new commands from zsh history files.

    Two modes:
    - Session mode (macOS): ~/.zsh_sessions/*.history + ~/.zsh_history
    - Standard mode: watch ~/.zsh_history directly
    """

    def __init__(self, home: Path | None = None):
        self._home = home or Path.home()
        self._trackers: list[_HistoryFileTracker] = []
        self._probed = False
        self._session_mode = False
        self._flush_counter = 0

    def probe(self) -> ProbeResult:
        paths = []
        warnings = []

        sessions_dir = self._home / ".zsh_sessions"
        has_sessions = sessions_dir.is_dir()
        standard = self._home / ".zsh_history"

        if has_sessions:
            # macOS session mode: watch .history files (NOT .historynew)
            for sf in sessions_dir.glob("*.history"):
                if sf.stat().st_size > 0:
                    paths.append(str(sf))
            # Also watch shared history (gets appended on every session close)
            if standard.exists():
                paths.append(str(standard))
        else:
            if standard.exists():
                paths.append(str(standard))
                if standard.stat().st_size == 0:
                    warnings.append("~/.zsh_history is empty")

        if not paths:
            desc = "no history files with data found" if has_sessions else "no history file found"
            return ProbeResult(
                available=False,
                source="zsh",
                description=desc,
                warnings=warnings or ["checked ~/.zsh_history and ~/.zsh_sessions/"],
            )

        mode = "session" if has_sessions else "standard"
        return ProbeResult(
            available=True,
            source="zsh",
            description=f"found {len(paths)} history source(s) ({mode} mode)",
            paths=paths,
            warnings=warnings,
        )

    def _ensure_probed(self):
        if self._probed:
            return
        sessions_dir = self._home / ".zsh_sessions"
        self._session_mode = sessions_dir.is_dir()
        result = self.probe()
        for p in result.paths:
            self._trackers.append(
                _HistoryFileTracker(Path(p), parser=_parse_zsh_line)
            )
        self._probed = True

    def collect(self) -> list[dict]:
        """Return new commands as records matching manifest db.columns."""
        self._ensure_probed()

        self._flush_counter += 1
        if self._flush_counter % 10 == 0:
            _signal_zsh_flush()

        if self._session_mode and self._flush_counter % 30 == 0:
            self._refresh_session_trackers()

        records = []
        seen_commands = set()
        timestamp = datetime.now(timezone.utc).isoformat()
        for tracker in self._trackers:
            for cmd in tracker.collect_new():
                # Dedup: same command may appear in both session .history and ~/.zsh_history
                if cmd not in seen_commands:
                    seen_commands.add(cmd)
                    records.append({
                        "timestamp": timestamp,
                        "command": cmd,
                    })
        return records

    def _refresh_session_trackers(self):
        """Check for new .history files that appeared since last probe."""
        sessions_dir = self._home / ".zsh_sessions"
        if not sessions_dir.is_dir():
            return
        tracked_paths = {t.path for t in self._trackers}
        for sf in sessions_dir.glob("*.history"):
            if sf not in tracked_paths and sf.stat().st_size > 0:
                self._trackers.append(
                    _HistoryFileTracker(sf, parser=_parse_zsh_line)
                )
                logger.info("zsh: new history file discovered: %s", sf)
