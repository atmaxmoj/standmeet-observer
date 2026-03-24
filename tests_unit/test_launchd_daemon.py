"""Integration tests for launchd-based source daemon management.

macOS only — tests that launchd auto-restarts killed source processes.
"""

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS only")

LABEL = "com.observer.test.dummy"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
UID = os.getuid()
DOMAIN_TARGET = f"gui/{UID}"


def _bootstrap(plist_path: Path):
    subprocess.run(["launchctl", "bootstrap", DOMAIN_TARGET, str(plist_path)], check=True)


def _bootout(label: str):
    subprocess.run(["launchctl", "bootout", f"{DOMAIN_TARGET}/{label}"], capture_output=True)


def _get_pid(label: str) -> int | None:
    result = subprocess.run(
        ["launchctl", "print", f"{DOMAIN_TARGET}/{label}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    match = re.search(r"pid\s*=\s*(\d+)", result.stdout)
    return int(match.group(1)) if match else None


def _is_loaded(label: str) -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"{DOMAIN_TARGET}/{label}"],
        capture_output=True,
    )
    return result.returncode == 0


@pytest.fixture
def dummy_plist(tmp_path):
    """Create a minimal launchd plist that runs a sleep loop."""
    import plistlib

    # Ensure clean state — bootout any leftover from previous run
    _bootout(LABEL)
    time.sleep(1)

    plist = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/sh", "-c", "while true; do sleep 1; done"],
        "KeepAlive": True,
        "RunAtLoad": True,
        "ThrottleInterval": 1,  # Reduce restart delay for tests
    }

    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    plist_path = PLIST_DIR / f"{LABEL}.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)

    yield plist_path

    _bootout(LABEL)
    plist_path.unlink(missing_ok=True)


class TestLaunchdDaemon:
    def test_launchd_starts_service(self, dummy_plist):
        """bootstrap loads and starts the service."""
        _bootstrap(dummy_plist)
        time.sleep(2)

        pid = _get_pid(LABEL)
        assert pid is not None, "Service should be running"
        assert pid > 0

    def test_launchd_restarts_after_kill(self, dummy_plist):
        """Kill the process → launchd restarts it with new PID."""
        _bootstrap(dummy_plist)
        time.sleep(2)

        pid1 = _get_pid(LABEL)
        assert pid1 is not None, "Service should be running"

        os.kill(pid1, signal.SIGKILL)

        # launchd may throttle restarts — wait up to 15s
        pid2 = None
        for _ in range(15):
            time.sleep(1)
            pid2 = _get_pid(LABEL)
            if pid2 is not None and pid2 != pid1:
                break

        assert pid2 is not None, "Service should have restarted"
        assert pid2 != pid1, f"Expected new PID after restart, got same {pid1}"

    def test_bootout_stops_service(self, dummy_plist):
        """bootout stops the service permanently."""
        _bootstrap(dummy_plist)
        time.sleep(2)

        assert _is_loaded(LABEL)

        _bootout(LABEL)
        time.sleep(1)

        assert not _is_loaded(LABEL), "Service should be stopped after bootout"


class TestOrphanCleanup:
    """Test that _kill_stale_processes finds and kills orphan source processes."""

    def test_kills_orphan_source_process(self, tmp_path):
        """Spawn a fake orphan process matching source pattern, verify cleanup kills it."""
        from cli import _kill_stale_processes

        # Create a fake "sources/builtin/testorphan" directory with a sleep process
        fake_dir = tmp_path / "sources" / "builtin" / "testorphan"
        fake_dir.mkdir(parents=True)

        # Start a process whose cmdline contains "sources/builtin/testorphan"
        orphan = subprocess.Popen(
            ["sh", "-c", f"exec -a 'python sources/builtin/testorphan/fake' sleep 300"],
            start_new_session=True,
        )
        time.sleep(0.5)

        # Verify it's running
        assert orphan.poll() is None, "Orphan process should be running"

        # _kill_stale_processes should find and kill it
        _kill_stale_processes("source-testorphan")
        time.sleep(1)

        # Process should be dead
        orphan.poll()
        assert orphan.returncode is not None, "Orphan process should have been killed"
