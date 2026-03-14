#!/usr/bin/env python3
"""Bisimulator CLI — cross-platform task runner.

Usage:
    npm run setup      # First-time install
    npm start          # Start everything
    npm stop           # Stop daemons + containers
    npm run down       # Stop + remove containers and volumes
    npm run restart    # Stop + start everything
    npm run status     # Check what's running
    npm run logs       # Docker compose logs
    npm test           # Run web Playwright tests
    npm run rebuild    # Rebuild Docker images
"""

import os
import signal
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = Path.home() / ".bisimulator"
PID_DIR = DATA_DIR / "pids"
LOG_DIR = DATA_DIR / "logs"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, **kwargs)


def check_prereqs():
    if not shutil.which("docker"):
        sys.exit("ERROR: Docker not found. Install Docker Desktop first.")
    r = run(["docker", "info"], capture_output=True)
    if r.returncode != 0:
        sys.exit("ERROR: Docker is not running. Start Docker Desktop and try again.")
    if not shutil.which("uv"):
        sys.exit("ERROR: uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/")


def platform_extra() -> str | None:
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform == "win32":
        return "windows"
    return None


# ── PID-based daemon management (cross-platform) ─────────────────────


def _pid_file(name: str) -> Path:
    return PID_DIR / f"{name}.pid"


def _log_file(name: str) -> Path:
    return LOG_DIR / f"{name}.log"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def daemon_running(name: str) -> int | None:
    """Return PID if daemon is running, else None."""
    pf = _pid_file(name)
    if not pf.exists():
        return None
    pid = int(pf.read_text().strip())
    if _pid_alive(pid):
        return pid
    pf.unlink(missing_ok=True)
    return None


def _kill_stale_processes(name: str):
    """Find and kill any orphaned processes for this daemon (not tracked by PID file)."""
    if sys.platform == "win32":
        return  # TODO: implement for Windows
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"python -m {name}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return
        tracked_pid = None
        pf = _pid_file(name)
        if pf.exists():
            tracked_pid = int(pf.read_text().strip())
        for line in result.stdout.strip().split("\n"):
            pid = int(line.strip())
            if pid != tracked_pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    print(f"  killed stale {name} process (pid {pid})")
                except OSError:
                    pass
    except Exception:
        pass


def daemon_start(name: str, cwd: Path):
    # Kill any orphaned processes before starting
    _kill_stale_processes(name)

    pid = daemon_running(name)
    if pid:
        print(f"  {name} already running (pid {pid})")
        return

    PID_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = _log_file(name)

    print(f"  Starting {name}...")
    with open(log, "w") as lf:
        kwargs = dict(cwd=cwd, stdout=lf, stderr=lf)
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        p = subprocess.Popen(["uv", "run", "python", "-m", name], **kwargs)

    _pid_file(name).write_text(str(p.pid))
    print(f"  {name} started (pid {p.pid}) → {log}")


def daemon_stop(name: str):
    pid = daemon_running(name)
    if pid:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            print(f"  {name} stopped (pid {pid})")
        except Exception as e:
            print(f"  {name} stop failed: {e}")
    else:
        print(f"  {name} not running")

    _pid_file(name).unlink(missing_ok=True)
    # Also kill any orphaned processes
    _kill_stale_processes(name)


# ── Commands ──────────────────────────────────────────────────────────


def cmd_setup():
    print("==> Checking prerequisites...")
    check_prereqs()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    env_file = ROOT / ".env"
    if not env_file.exists():
        example = ROOT / ".env.example"
        if example.exists():
            shutil.copy(example, env_file)
            print("  Copied .env.example → .env")
            print("  !! Edit .env and set ANTHROPIC_API_KEY before starting")
        else:
            sys.exit("ERROR: No .env or .env.example found. Create .env with ANTHROPIC_API_KEY=sk-ant-...")

    extra = platform_extra()
    if extra:
        print(f"==> Installing capture daemon ({extra})...")
        run(["uv", "sync", "--extra", extra], cwd=ROOT / "capture")

    print("==> Installing audio daemon...")
    run(["uv", "sync"], cwd=ROOT / "audio")

    print("==> Building Docker images...")
    run(["docker", "compose", "build"], cwd=ROOT)

    print("\n==> Setup complete! Run: npm start")


def check_macos_permissions():
    """On macOS, verify screen recording + microphone permissions."""
    if sys.platform != "darwin":
        return

    # Screen recording: try a test capture
    try:
        result = subprocess.run(
            ["uv", "run", "python", "-c",
             "from capture.backends.macos import check_screen_recording_permission; "
             "import sys; sys.exit(0 if check_screen_recording_permission() else 1)"],
            cwd=ROOT / "capture", capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print("  !! Screen recording permission DENIED")
            print("  !! Go to System Settings → Privacy & Security → Screen Recording")
            print("  !! Enable access for Terminal (or your terminal app), then restart")
            sys.exit(1)
        print("  Screen recording permission: OK")
    except Exception as e:
        print(f"  !! Could not check screen recording permission: {e}")

    # Microphone: try opening a stream
    try:
        result = subprocess.run(
            ["uv", "run", "python", "-c",
             "import sounddevice as sd; "
             "s = sd.InputStream(samplerate=16000, channels=1); s.start(); s.stop(); s.close(); "
             "print('OK')"],
            cwd=ROOT / "audio", capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or "OK" not in result.stdout:
            print("  !! Microphone permission DENIED")
            print("  !! Go to System Settings → Privacy & Security → Microphone")
            print("  !! Enable access for Terminal (or your terminal app), then restart")
            sys.exit(1)
        print("  Microphone permission: OK")
    except Exception as e:
        print(f"  !! Could not check microphone permission: {e}")


def cmd_start():
    print("==> Starting bisimulator...")
    check_prereqs()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    extra = platform_extra()
    if extra:
        print("==> Checking permissions...")
        check_macos_permissions()
        daemon_start("capture", ROOT / "capture")
    daemon_start("audio", ROOT / "audio")

    print("==> Building + starting engine + web containers...")
    run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT)

    print()
    print("  Dashboard:  http://localhost:5174")
    print("  API:        http://localhost:5001")


def cmd_stop():
    print("==> Stopping bisimulator...")
    daemon_stop("capture")
    daemon_stop("audio")
    run(["docker", "compose", "down"], cwd=ROOT)
    print("==> Stopped")


def cmd_status():
    for name in ("capture", "audio"):
        pid = daemon_running(name)
        status = f"RUNNING (pid {pid})" if pid else "NOT RUNNING"
        print(f"  {name}: {status}")

    db = DATA_DIR / "capture.db"
    if db.exists():
        print(f"  capture DB: {db} ({db.stat().st_size / 1_000_000:.1f} MB)")

    print()
    run(["docker", "compose", "ps"], cwd=ROOT)

    print()
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:5001/engine/status", timeout=3) as r:
            print(f"  API: {r.read().decode()}")
    except Exception:
        print("  API: NOT REACHABLE")


def cmd_logs():
    run(["docker", "compose", "logs", "-f"], cwd=ROOT)


def cmd_test():
    print("==> Running Playwright tests...")
    run(["npx", "playwright", "test"], cwd=ROOT / "web")


def cmd_rebuild():
    print("==> Rebuilding containers...")
    run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT)


def cmd_down():
    """Stop and remove containers + volumes (clean slate)."""
    print("==> Tearing down containers...")
    run(["docker", "compose", "down", "-v"], cwd=ROOT)
    print("==> Containers and volumes removed")


def cmd_restart():
    """Restart everything (stop + start)."""
    cmd_stop()
    cmd_start()


COMMANDS = {
    "setup": cmd_setup,
    "start": cmd_start,
    "stop": cmd_stop,
    "down": cmd_down,
    "restart": cmd_restart,
    "status": cmd_status,
    "logs": cmd_logs,
    "test": cmd_test,
    "rebuild": cmd_rebuild,
}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("Commands:", ", ".join(COMMANDS))
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
