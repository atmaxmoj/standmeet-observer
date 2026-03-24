"""Integration test: shell watchdog restarts source after child process dies.

Starts a real daemon process with the watchdog wrapper, kills the child,
and verifies a new child appears.
"""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest


def _find_child_pid(wrapper_pid: int) -> int | None:
    """Find the child PID of the shell wrapper."""
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(wrapper_pid)],
            capture_output=True, text=True,
        )
        pids = [int(p.strip()) for p in result.stdout.strip().split("\n") if p.strip()]
        return pids[0] if pids else None
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


@pytest.fixture
def dummy_source(tmp_path):
    """Create a minimal source that runs forever (sleep loop)."""
    src_dir = tmp_path / "src" / "dummy_source"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("""
from source_framework.plugin import SourcePlugin, ProbeResult
import time

class DummySource(SourcePlugin):
    def probe(self):
        return ProbeResult(available=True, source="dummy", description="test")

    def collect(self):
        return []

    def start(self, client, config):
        while True:
            time.sleep(1)
""")
    (tmp_path / "manifest.json").write_text("""{
        "name": "dummy",
        "version": "0.1.0",
        "entrypoint": "dummy_source:DummySource",
        "db": {"table": "dummy_data", "columns": {}},
        "platform": ["darwin", "linux", "win32"]
    }""")
    return tmp_path


class TestWatchdogIntegration:
    def test_watchdog_restarts_killed_child(self, dummy_source):
        """Kill the source child process → watchdog shell restarts it."""
        log = dummy_source / "test.log"

        with open(log, "w") as lf:
            wrapper = subprocess.Popen(
                [
                    "sh", "-c",
                    'while true; do uv run python -m source_framework . ; '
                    'echo "[watchdog] restarting..." >&2; sleep 1; done',
                ],
                cwd=dummy_source,
                stdout=lf, stderr=lf,
                start_new_session=True,
            )

        try:
            # Wait for child to start
            child_pid = None
            for _ in range(20):
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
            for _ in range(20):
                time.sleep(0.5)
                new_child = _find_child_pid(wrapper.pid)
                if new_child and new_child != child_pid:
                    break

            assert new_child is not None, "Watchdog did not restart child"
            assert new_child != child_pid, f"Expected new PID, got same {child_pid}"
            assert _pid_alive(new_child), "New child should be alive"

        finally:
            # Clean up: kill wrapper (which kills child too)
            try:
                os.killpg(os.getpgid(wrapper.pid), signal.SIGTERM)
            except OSError:
                pass
            wrapper.wait(timeout=5)
