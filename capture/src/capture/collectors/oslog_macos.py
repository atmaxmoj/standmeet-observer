"""macOS os_log collector — streams system events via `log stream`.

Runs `log stream --style json --predicate '...'` as a subprocess,
parses JSON output, classifies events into categories:
- app_launch, app_quit, frontmost_change
- sleep, wake, lock, unlock
"""

import json
import logging
import subprocess
import threading
from collections import deque
from pathlib import Path

from capture.collectors.base import BaseCollector, ProbeResult

logger = logging.getLogger(__name__)

# Predicate for useful system events
PREDICATE = (
    '(subsystem == "com.apple.runningboard") OR '
    '(process == "powerd" AND eventMessage CONTAINS "sleepWake") OR '
    '(process == "loginwindow")'
)


def _classify_runningboard(msg: str) -> str | None:
    if "frontmost" in msg.lower():
        return "frontmost_change"
    if "Now tracking" in msg or "launch" in msg.lower():
        return "app_launch"
    if "termination" in msg.lower() or "process exit" in msg.lower():
        return "app_quit"
    return None


def _classify_power(msg: str) -> str | None:
    if "sleepWake" in msg or "Sleep" in msg:
        return "sleep"
    if "Wake" in msg:
        return "wake"
    return None


def _classify_loginwindow(msg: str) -> str | None:
    msg_lower = msg.lower()
    if "unlock" in msg_lower:
        return "unlock"
    if "lock" in msg_lower:
        return "lock"
    return None


def classify_event(entry: dict) -> str | None:
    """Classify an os_log entry into a category. Returns None if not useful."""
    msg = entry.get("eventMessage", "")
    process_path = entry.get("processImagePath", "")

    if entry.get("subsystem") == "com.apple.runningboard":
        return _classify_runningboard(msg)
    if "powerd" in process_path:
        return _classify_power(msg)
    if "loginwindow" in process_path:
        return _classify_loginwindow(msg)
    return None


def format_event(entry: dict, category: str) -> str:
    """Format an os_log entry into a human-readable string for storage."""
    msg = entry.get("eventMessage", "")
    process = entry.get("processImagePath", "").rsplit("/", 1)[-1]
    return f"[{category}] {process}: {msg[:300]}"


def parse_json_stream(line: str) -> dict | None:
    """Parse a single line from `log stream --style json`.

    Used for single-line JSON entries. For pretty-printed multi-line
    entries, use parse_json_stream_multiline() instead.
    """
    line = line.strip()
    if not line or line in ("[", "]"):
        return None
    if line.startswith("[{"):
        line = line[1:]
    if line.startswith(",{"):
        line = line[1:]
    if line.endswith("},"):
        line = line[:-1]
    if line.endswith("}]"):
        line = line[:-1]

    if not line.startswith("{"):
        return None

    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def parse_json_stream_multiline(stream) -> list[dict]:
    """Parse pretty-printed `log stream --style json` output.

    The format is a JSON array with multi-line entries:
    [{
      "key": "value",
      ...
    },{
      ...
    }]

    We accumulate lines into a buffer and split on '},{'."""
    buf = []
    for raw_line in stream:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
        buf.append(line)

    text = "".join(buf).strip()
    # Remove filter description line at the top
    if text.startswith("Filtering"):
        text = text[text.index("\n") + 1:].strip()

    if not text:
        return []

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: try splitting on },{
    entries = []
    # Strip outer [ ]
    if text.startswith("["):
        text = text[1:]
    if text.endswith("]"):
        text = text[:-1]
    # Split on },{
    chunks = text.split("},{")
    for i, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk.startswith("{"):
            chunk = "{" + chunk
        if not chunk.endswith("}"):
            chunk = chunk + "}"
        try:
            entries.append(json.loads(chunk))
        except json.JSONDecodeError:
            continue
    return entries


class OsLogCollector(BaseCollector):
    """Streams macOS os_log events via `log stream` subprocess.

    A background thread reads the subprocess stdout, parses JSON,
    classifies events, and buffers them. `collect()` drains the buffer.
    """

    event_type = "os_log"
    source = "macos"

    def __init__(self, command: list[str] | None = None, stdin=None):
        self._command = command or [
            "log", "stream", "--style", "json", "--level", "info",
            "--predicate", PREDICATE,
        ]
        self._stdin = stdin  # For testing: read from stdin instead of subprocess
        self._buffer: deque[tuple[str, str, str]] = deque(maxlen=1000)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._started = False

    def probe(self) -> ProbeResult:
        # Check if `log` command exists (macOS only)
        log_path = Path("/usr/bin/log")
        if not log_path.exists():
            return ProbeResult(
                available=False,
                source="macos",
                description="log command not found (not macOS?)",
            )
        return ProbeResult(
            available=True,
            source="macos",
            description="os_log stream via /usr/bin/log",
            paths=[str(log_path)],
        )

    def _reader(self, stream):
        """Background thread: read lines, parse, classify, buffer.

        `log stream --style json` outputs pretty-printed JSON, so we
        accumulate lines and parse multi-line entries.
        """
        entries = parse_json_stream_multiline(stream)
        for entry in entries:
            category = classify_event(entry)
            if category is None:
                continue
            timestamp = entry.get("timestamp", "")
            data = format_event(entry, category)
            self._buffer.append((timestamp, category, data))

    def _start(self):
        if self._started:
            return
        self._started = True

        if self._stdin is not None:
            # Test mode: read from provided stream
            self._thread = threading.Thread(
                target=self._reader, args=(self._stdin,), daemon=True,
            )
            self._thread.start()
            return

        try:
            self._proc = subprocess.Popen(
                self._command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._thread = threading.Thread(
                target=self._reader, args=(self._proc.stdout,), daemon=True,
            )
            self._thread.start()
            logger.info("os_log stream started (pid %d)", self._proc.pid)
        except Exception:
            logger.exception("failed to start log stream")

    def collect(self) -> list[str]:
        self._start()
        events = []
        while self._buffer:
            timestamp, category, data = self._buffer.popleft()
            events.append(data)
        return events


COLLECTORS = [
    ("darwin", OsLogCollector),
]
