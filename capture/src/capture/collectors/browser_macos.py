"""Browser URL collectors for macOS using AppleScript."""

import logging
import subprocess

from capture.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


def _is_app_running(app_name: str) -> bool:
    """Check if an app is running via AppleScript (without activating it)."""
    try:
        result = subprocess.run(
            ["osascript", "-e",
             f'tell application "System Events" to (name of processes) contains "{app_name}"'],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


class SafariURLCollector(BaseCollector):
    """Gets the active Safari tab URL via AppleScript.

    Works even when Safari is NOT the frontmost app — we query Safari
    directly as long as it's running.
    """

    event_type = "browser_url"
    source = "safari"

    def __init__(self):
        self._last_url = ""

    def available(self) -> bool:
        return True

    def collect(self) -> list[str]:
        try:
            if not _is_app_running("Safari"):
                return []

            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "Safari" to return URL of current tab of front window'],
                capture_output=True, text=True, timeout=3,
            )
            url = result.stdout.strip()
            if not url or url == "missing value" or url == self._last_url:
                return []

            self._last_url = url
            logger.debug("safari: %s", url)
            return [url]

        except subprocess.TimeoutExpired:
            return []
        except Exception:
            logger.debug("safari: not running or not accessible")
            return []


class ChromeURLCollector(BaseCollector):
    """Gets the active Chrome tab URL via AppleScript.

    Works even when Chrome is NOT the frontmost app — we query Chrome
    directly as long as it's running.
    """

    event_type = "browser_url"
    source = "chrome"

    def __init__(self):
        self._last_url = ""

    def available(self) -> bool:
        return True

    def collect(self) -> list[str]:
        try:
            if not _is_app_running("Google Chrome"):
                return []

            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "Google Chrome" to return URL of active tab of front window'],
                capture_output=True, text=True, timeout=3,
            )
            url = result.stdout.strip()
            if not url or url == "missing value" or url == self._last_url:
                return []

            self._last_url = url
            logger.debug("chrome: %s", url)
            return [url]

        except subprocess.TimeoutExpired:
            return []
        except Exception:
            logger.debug("chrome: not running or not accessible")
            return []


COLLECTORS = [
    ("darwin", SafariURLCollector),
    ("darwin", ChromeURLCollector),
]
