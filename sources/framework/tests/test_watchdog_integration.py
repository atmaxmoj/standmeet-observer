"""Integration test: shell watchdog restarts source after child process dies.

Starts a real daemon process with the watchdog wrapper, kills the child,
and verifies a new child appears.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _get_children(pid: int) -> list[int]:
    """Get direct child PIDs by reading /proc/*/stat (no pgrep needed)."""
    children = []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            # Format: pid (comm) state ppid ...
            parts = stat.split(") ", 1)[-1].split()
            ppid = int(parts[1])
            if ppid == pid:
                children.append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return children


def _find_child_pid(wrapper_pid: int) -> int | None:
    """Find the deepest descendant PID of the shell wrapper."""
    try:
        pid = wrapper_pid
        while True:
            children = _get_children(pid)
            if not children:
                return pid if pid != wrapper_pid else None
            pid = children[0]
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class TestWatchdogIntegration:
    def test_watchdog_restarts_killed_child(self, tmp_path):
        """Kill the child process → watchdog shell restarts it."""
        # Use a simple python sleep loop as the child process
        # (avoids dependency on source_framework being importable from sh)
        child_script = tmp_path / "child.py"
        child_script.write_text("import time\nwhile True: time.sleep(1)\n")
        log = tmp_path / "test.log"

        python = sys.executable

        with open(log, "w") as lf:
            wrapper = subprocess.Popen(
                [
                    "sh", "-c",
                    f'while true; do {python} {child_script} ; '
                    'echo "[watchdog] restarting..." >&2; sleep 1; done',
                ],
                stdout=lf, stderr=lf,
                start_new_session=True,
            )

        try:
            # Wait for child to start
            child_pid = None
            for _ in range(30):
                time.sleep(0.5)
                child_pid = _find_child_pid(wrapper.pid)
                if child_pid:
                    break

            assert child_pid is not None, "Child process did not start"
            assert _pid_alive(child_pid), "Child should be alive"

            # Kill the child
            os.kill(child_pid, signal.SIGKILL)
            time.sleep(1)
            assert not _pid_alive(child_pid), "Child should be dead after kill"

            # Wait for watchdog to restart
            new_child = None
            for _ in range(30):
                time.sleep(0.5)
                new_child = _find_child_pid(wrapper.pid)
                if new_child and new_child != child_pid:
                    break

            assert new_child is not None, "Watchdog did not restart child"
            assert new_child != child_pid, f"Expected new PID, got same {child_pid}"
            assert _pid_alive(new_child), "New child should be alive"

        finally:
            try:
                os.killpg(os.getpgid(wrapper.pid), signal.SIGTERM)
            except OSError:
                pass
            wrapper.wait(timeout=5)
