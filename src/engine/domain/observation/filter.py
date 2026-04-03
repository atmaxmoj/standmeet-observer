"""Observation filtering — noise removal + batch window detection.

Rules-based, no LLM, $0 cost. Pure functions operating on Frame entities.
"""

import re
import logging
from datetime import datetime, timezone

from engine.domain.observation.entity import Frame

logger = logging.getLogger(__name__)

# Apps that produce noise, not signal
IGNORE_APPS = frozenset(
    {
        "Finder",
        "SystemUIServer",
        "Dock",
        "loginwindow",
        "Spotlight",
        "NotificationCenter",
        "Control Center",
        "WindowManager",
        "ScreenSaverEngine",
        # CI/build processes — not user activity
        "chrome-headless-shell",
        "dartvm",
        "dart",
        "dartaotruntime",
        # macOS system services
        "AXVisualSupportAgent",
        "SteamClean",
        "com.apple.Safari.CacheDeleteExtension",
        "com.apple.TV.CacheDeleteExtension",
        "com.apple.Music.CacheDeleteExtension",
        "com.apple.Mail.CacheDeleteExtension",
    }
)

# Processes spawned by observer itself (source plugins use osascript, node, caffeinate).
# These show up in oslog as [anon<processname>(uid):pid] — filter them to avoid
# observer observing itself and creating junk episodes every ~3 minutes.
_OBSERVER_PROCESS_RE = re.compile(r"\[anon<(osascript|node|caffeinate)\>\(\d+\):\d+\]")

MIN_TEXT_LENGTH = 10

# Screen captures of Terminal showing only observer process output.
# Matches when the text is dominated by osascript/caffeinate/node process lines
# with no real user commands.
_OBSERVER_TERMINAL_TOKENS = frozenset({"osascript", "caffeinate"})
_OBSERVER_TERMINAL_THRESHOLD = 0.15  # if >15% of words are observer process tokens → noise


_CODE_KEYWORDS = frozenset({"def", "class", "import", "from", "function", "const", "return", "if", "else", "for", "while"})


def _is_terminal_observer_noise(text: str) -> bool:
    """Check if screen capture text is dominated by observer process noise.

    Returns False if text contains code keywords (likely viewing source code).
    """
    words = text.lower().split()
    if len(words) < 5:
        return False
    # If text looks like source code, keep it
    if any(w in _CODE_KEYWORDS for w in words):
        return False
    noise_count = sum(1 for w in words if any(t in w for t in _OBSERVER_TERMINAL_TOKENS))
    return noise_count / len(words) > _OBSERVER_TERMINAL_THRESHOLD


def should_keep(frame: Frame) -> bool:
    reason = _filter_reason(frame)
    if reason:
        logger.debug("filtered out %s id=%d (%s)", frame.source, frame.id, reason)
        return False
    return True


def _filter_reason(frame: Frame) -> str | None:
    """Return filter reason string, or None if frame should be kept."""
    # Event sources: check text + observer noise
    if frame.source in ("os_event", "audio", "oslog"):
        if not frame.text or not frame.text.strip():
            return "empty text"
        return "observer process noise" if _OBSERVER_PROCESS_RE.search(frame.text) else None

    # Screen captures: check Terminal observer noise, ignored apps, text length
    if frame.source == "capture" and frame.text and _is_terminal_observer_noise(frame.text):
        return "observer process noise in screen capture"
    if frame.app_name in IGNORE_APPS:
        return f"ignored app: {frame.app_name}"
    if not frame.text or len(frame.text.strip()) < MIN_TEXT_LENGTH:
        return "text too short"
    return None


def detect_windows(
    frames: list[Frame],
    window_minutes: int = 30,
    idle_seconds: int = 300,
) -> tuple[list[list[Frame]], list[Frame]]:
    """Split sorted frames into time windows. Returns (complete_windows, remainder).

    A window closes when:
    - Gap between consecutive frames > idle_seconds (user went AFK)
    - Time span from first to current frame > window_minutes

    The last group is only emitted if the most recent frame is older than
    idle_seconds from now (meaning the user has stopped). Otherwise it stays
    as remainder for the next check.
    """
    if not frames:
        return [], []

    windows: list[list[Frame]] = []
    current: list[Frame] = [frames[0]]

    for f in frames[1:]:
        try:
            prev_ts = datetime.fromisoformat(current[-1].timestamp)
            curr_ts = datetime.fromisoformat(f.timestamp)
            start_ts = datetime.fromisoformat(current[0].timestamp)
        except (ValueError, TypeError):
            current.append(f)
            continue

        gap = (curr_ts - prev_ts).total_seconds()
        span = (curr_ts - start_ts).total_seconds()

        if gap > idle_seconds or span > window_minutes * 60:
            windows.append(current)
            current = [f]
        else:
            current.append(f)

    # Only emit the last group if the user has been idle long enough
    if current:
        try:
            last_ts = datetime.fromisoformat(current[-1].timestamp)
            now = datetime.now(timezone.utc)
            if last_ts.tzinfo is None:
                now = now.replace(tzinfo=None)
            if (now - last_ts).total_seconds() > idle_seconds:
                windows.append(current)
                current = []
        except (ValueError, TypeError):
            pass

    return windows, current
