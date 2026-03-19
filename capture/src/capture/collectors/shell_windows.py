"""Shell history collectors for Windows (PowerShell + Git Bash)."""

import logging
import os
from pathlib import Path

from capture.collectors.base import BaseCollector, ProbeResult

logger = logging.getLogger(__name__)


def _is_noise(cmd: str) -> bool:
    """Filter out trivial commands."""
    trivial = {"ls", "cd", "pwd", "cls", "clear", "exit", "dir", "history", "Get-History"}
    first_word = cmd.split()[0] if cmd.split() else ""
    return first_word in trivial


class _HistoryFileTracker:
    """Tracks a single history file for new lines."""

    def __init__(self, path: Path):
        self.path = path
        self._last_size = 0
        self._last_line_count = 0

    def collect_new(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            size = self.path.stat().st_size
            if size <= self._last_size:
                return []

            with open(self.path, "r", errors="replace") as f:
                lines = f.readlines()

            if self._last_line_count == 0:
                self._last_line_count = len(lines)
                self._last_size = size
                return []

            new_lines = lines[self._last_line_count:]
            self._last_line_count = len(lines)
            self._last_size = size

            commands = []
            for line in new_lines:
                cmd = line.strip()
                if cmd and not _is_noise(cmd):
                    commands.append(cmd)
            return commands
        except Exception:
            logger.exception("failed to read %s", self.path)
            return []


class PowerShellHistoryCollector(BaseCollector):
    """Reads new commands from PowerShell ConsoleHost_history.txt.

    Probes standard PSReadLine locations for both PS 5.x and 7+.
    """

    event_type = "shell_command"
    source = "powershell"

    def __init__(self, appdata: Path | None = None):
        if appdata is None:
            appdata = Path(os.environ.get("APPDATA", ""))
        self._appdata = appdata
        self._paths = self._candidate_paths()
        self._tracker: _HistoryFileTracker | None = None
        self._active_path: Path | None = None

    def _candidate_paths(self) -> list[Path]:
        """All known PowerShell history file locations."""
        return [
            # Standard PSReadLine path (PS 5.x and 7+ on Windows share this)
            self._appdata / "Microsoft" / "Windows" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt",
            # VS Code integrated terminal uses different host name
            self._appdata / "Microsoft" / "Windows" / "PowerShell" / "PSReadLine" / "Visual Studio Code Host_history.txt",
        ]

    def probe(self) -> ProbeResult:
        found = [p for p in self._paths if p.exists()]
        if not found:
            return ProbeResult(
                available=False,
                source="powershell",
                description="no PSReadLine history found",
                warnings=[f"checked {len(self._paths)} candidate paths"],
            )
        return ProbeResult(
            available=True,
            source="powershell",
            description=f"found {len(found)} history file(s)",
            paths=[str(p) for p in found],
        )

    def collect(self) -> list[str]:
        if self._tracker is None:
            # Use first available path
            for p in self._paths:
                if p.exists():
                    self._active_path = p
                    self._tracker = _HistoryFileTracker(p)
                    break
            if self._tracker is None:
                return []
        return self._tracker.collect_new()


class GitBashHistoryCollector(BaseCollector):
    """Reads new commands from Git Bash (~/.bash_history on Windows)."""

    event_type = "shell_command"
    source = "git_bash"

    def __init__(self, home: Path | None = None):
        if home is None:
            home = Path(os.environ.get("USERPROFILE", Path.home()))
        self._home = home
        self._path = self._home / ".bash_history"
        self._tracker: _HistoryFileTracker | None = None

    def probe(self) -> ProbeResult:
        if not self._path.exists():
            return ProbeResult(
                available=False,
                source="git_bash",
                description="no .bash_history found",
                warnings=[f"checked {self._path}"],
            )
        return ProbeResult(
            available=True,
            source="git_bash",
            description="found .bash_history (Git Bash)",
            paths=[str(self._path)],
        )

    def collect(self) -> list[str]:
        if not self._path.exists():
            return []
        if self._tracker is None:
            self._tracker = _HistoryFileTracker(self._path)
        return self._tracker.collect_new()


COLLECTORS = [
    ("win32", PowerShellHistoryCollector),
    ("win32", GitBashHistoryCollector),
]
