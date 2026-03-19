"""Shell history collectors for macOS (zsh + bash)."""

import logging
import os
import signal
import subprocess
from pathlib import Path

from capture.collectors.base import BaseCollector, ProbeResult

logger = logging.getLogger(__name__)


def _signal_zsh_flush():
    """Send SIGUSR1 to running zsh processes to trigger history write.

    This works when SHARE_HISTORY is set (zsh re-reads/writes history on
    SIGUSR1). With INC_APPEND_HISTORY each command is written immediately
    and this signal is unnecessary but harmless.
    """
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
    # Extended format: `: 1234567890:0;actual command`
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


class ZshHistoryCollector(BaseCollector):
    """Reads new commands from zsh history files.

    Two mutually exclusive modes:
    - Session mode: ~/.zsh_sessions/ exists → watch only *.historynew files.
      ~/.zsh_history is a merge target on session close, watching it would
      duplicate events already seen from .historynew.
    - Standard mode: no sessions dir → watch ~/.zsh_history directly.
    """

    event_type = "shell_command"
    source = "zsh"

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
            # Session mode: only watch active .historynew files
            active_sessions = list(sessions_dir.glob("*.historynew"))
            for sf in active_sessions:
                paths.append(str(sf))
            if standard.exists():
                warnings.append("~/.zsh_history exists but skipped (session mode — it is a merge target)")
        else:
            # Standard mode: watch ~/.zsh_history
            if standard.exists():
                paths.append(str(standard))
                if standard.stat().st_size == 0:
                    warnings.append("~/.zsh_history is empty")

        if not paths:
            desc = "no active session files found" if has_sessions else "no history file found"
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

    def collect(self) -> list[str]:
        self._ensure_probed()

        self._flush_counter += 1
        if self._flush_counter % 10 == 0:
            _signal_zsh_flush()

        # Re-probe for new session files every 30 cycles (~90s)
        if self._session_mode and self._flush_counter % 30 == 0:
            self._refresh_session_trackers()

        commands = []
        for tracker in self._trackers:
            commands.extend(tracker.collect_new())
        return commands

    def _refresh_session_trackers(self):
        """Check for new .historynew files that appeared since last probe."""
        sessions_dir = self._home / ".zsh_sessions"
        if not sessions_dir.is_dir():
            return
        tracked_paths = {t.path for t in self._trackers}
        for sf in sessions_dir.glob("*.historynew"):
            if sf not in tracked_paths:
                self._trackers.append(
                    _HistoryFileTracker(sf, parser=_parse_zsh_line)
                )
                logger.info("zsh: new session file discovered: %s", sf)


class BashHistoryCollector(BaseCollector):
    """Reads new commands from ~/.bash_history."""

    event_type = "shell_command"
    source = "bash"

    def __init__(self, home: Path | None = None):
        self._home = home or Path.home()
        self._path = self._home / ".bash_history"
        self._tracker: _HistoryFileTracker | None = None

    def probe(self) -> ProbeResult:
        if not self._path.exists():
            return ProbeResult(
                available=False,
                source="bash",
                description="no history file found",
                warnings=["checked ~/.bash_history"],
            )
        warnings = []
        if self._path.stat().st_size == 0:
            warnings.append("~/.bash_history is empty")
        return ProbeResult(
            available=True,
            source="bash",
            description="found ~/.bash_history",
            paths=[str(self._path)],
            warnings=warnings,
        )

    def collect(self) -> list[str]:
        if not self._path.exists():
            return []
        if self._tracker is None:
            self._tracker = _HistoryFileTracker(self._path)
        return self._tracker.collect_new()


COLLECTORS = [
    ("darwin", ZshHistoryCollector),
    ("darwin", BashHistoryCollector),
]
