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
    }
)

# Processes spawned by observer itself (source plugins use osascript, node, caffeinate).
# These show up in oslog as [anon<processname>(uid):pid] — filter them to avoid
# observer observing itself and creating junk episodes every ~3 minutes.
_OBSERVER_PROCESS_RE = re.compile(r"\[anon<(osascript|node|caffeinate)\>\(\d+\):\d+\]")

MIN_TEXT_LENGTH = 10


def should_keep(frame: Frame) -> bool:
    if frame.source in ("os_event", "audio"):
        if not frame.text or not frame.text.strip():
            logger.debug("filtered out %s id=%d (empty text)", frame.source, frame.id)
            return False
        if _OBSERVER_PROCESS_RE.search(frame.text):
            logger.debug("filtered out oslog id=%d (observer process noise)", frame.id)
            return False
        return True
    if frame.app_name in IGNORE_APPS:
        logger.debug("filtered out frame id=%d app=%s (ignored app)", frame.id, frame.app_name)
        return False
    if not frame.text or len(frame.text.strip()) < MIN_TEXT_LENGTH:
        logger.debug(
            "filtered out frame id=%d app=%s (text too short: %d chars)",
            frame.id, frame.app_name, len(frame.text.strip()) if frame.text else 0,
        )
        return False
    return True


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
