#!/usr/bin/env python3
"""Observer CLI — cross-platform task runner.

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
DATA_DIR = Path.home() / ".observer"
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
    print("==> Starting observer...")
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
    print("==> Stopping observer...")
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
    """Run tests. Usage: npm test [-- <suite>]
    Suites: capture, audio, engine, web, all (default: all)
    """
    suite = sys.argv[2] if len(sys.argv) > 2 else "all"
    results = []

    # Run code checks first (same as pre-commit hooks)
    print("==> Running code checks...")
    checks = [
        ("ruff", ["uv", "run", "ruff", "check", "src/", "tests/"], ROOT),
        ("tsc", ["npx", "tsc", "--noEmit"], ROOT / "web"),
        ("eslint", ["npx", "eslint", "src/", "--max-warnings", "0"], ROOT / "web"),
        ("knip", ["npx", "knip"], ROOT / "web"),
    ]
    for name, cmd, cwd in checks:
        r = run(cmd, cwd=cwd)
        if r.returncode != 0:
            print(f"\n==> CODE CHECK FAILED: {name}")
            sys.exit(1)
    print("==> All code checks passed\n")

    extra = platform_extra()

    if suite in ("capture", "all") and extra:
        print("==> Running capture pytest...")
        r = run(["uv", "run", "--extra", extra, "--extra", "test", "pytest", "-v"],
                cwd=ROOT / "capture")
        results.append(("capture", r.returncode))

    if suite in ("audio", "all"):
        print("\n==> Running audio pytest...")
        r = run(["uv", "run", "--extra", "test", "pytest", "-v"], cwd=ROOT / "audio")
        results.append(("audio", r.returncode))

    results_dir = ROOT / "tests" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    if suite in ("engine", "all"):
        print("\n==> Running engine pytest...")
        test_env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "sk-fake-test-key"),
            "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        }
        engine_log = results_dir / "engine.log"
        with open(engine_log, "w") as log:
            r = subprocess.run(
                ["uv", "run", "--extra", "test", "pytest", "-v",
                 f"--junitxml={results_dir / 'engine.xml'}"],
                cwd=ROOT, env=test_env, stdout=log, stderr=subprocess.STDOUT,
            )
        results.append(("engine", r.returncode))
        if r.returncode != 0:
            print(f"  See {engine_log}")

    if suite in ("web", "all"):
        print("\n==> Running Playwright tests (Docker)...")
        compose_test = str(ROOT / "docker-compose.test.yml")
        run(["docker", "compose", "-p", "bisimulator-test", "-f", compose_test,
             "up", "-d", "--build", "--wait", "engine-test"], cwd=ROOT)
        web_log = results_dir / "web.log"
        with open(web_log, "w") as log:
            r = subprocess.run(
                ["docker", "compose", "-p", "bisimulator-test", "-f", compose_test,
                 "run", "--rm", "playwright"],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            )
        results.append(("web", r.returncode))
        # Copy Playwright report from container if available
        run(["docker", "compose", "-p", "bisimulator-test", "-f", compose_test,
             "cp", "engine-test:/data/.", str(results_dir / "web-data")],
            cwd=ROOT)
        run(["docker", "compose", "-p", "bisimulator-test", "-f", compose_test,
             "down", "-v"], cwd=ROOT)
        if r.returncode != 0:
            print(f"  See {web_log}")

    if not results:
        print(f"Unknown suite: {suite}. Available: capture, audio, web, all")
        sys.exit(1)

    failed = [name for name, rc in results if rc != 0]
    if failed:
        print(f"\n==> FAILED: {', '.join(failed)}")
        sys.exit(1)
    print("\n==> ALL TESTS PASSED")


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


def _launchd_plist(name: str, cwd: Path) -> str:
    """Generate a launchd plist for a daemon."""
    uv_path = shutil.which("uv") or "/usr/local/bin/uv"
    label = f"com.observer.{name}"
    log = str(LOG_DIR / f"{name}.log")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{uv_path}</string>
        <string>run</string>
        <string>python</string>
        <string>-m</string>
        <string>{name}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{cwd}</string>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}</string>
    </dict>
</dict>
</plist>"""


def _plist_path(name: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"com.observer.{name}.plist"


def cmd_watchdog():
    """Install launchd plists for capture + audio with KeepAlive auto-restart."""
    if sys.platform != "darwin":
        sys.exit("launchd watchdog is macOS only")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Stop old PID-based daemons first
    for name in ("capture", "audio"):
        daemon_stop(name)

    daemons = [
        ("capture", ROOT / "capture"),
        ("audio", ROOT / "audio"),
    ]

    for name, cwd in daemons:
        plist_dst = _plist_path(name)
        plist_dst.parent.mkdir(parents=True, exist_ok=True)
        plist_dst.write_text(_launchd_plist(name, cwd))
        # Unload first (ignore errors if not loaded)
        run(["launchctl", "unload", str(plist_dst)], capture_output=True)
        run(["launchctl", "load", str(plist_dst)])
        print(f"  {name}: installed + loaded ({plist_dst})")

    print("\n  Daemons will auto-restart on crash.")
    print("  Use the dashboard toggle to pause/resume capture.")
    print("  To uninstall: npm run watchdog-off")


def cmd_watchdog_off():
    """Uninstall launchd plists."""
    if sys.platform != "darwin":
        sys.exit("launchd watchdog is macOS only")

    for name in ("capture", "audio"):
        plist = _plist_path(name)
        if plist.exists():
            run(["launchctl", "unload", str(plist)], capture_output=True)
            plist.unlink()
            print(f"  {name}: unloaded + removed")
        else:
            print(f"  {name}: not installed")


def cmd_experiment():
    """Run prompt experiment inside Docker container.

    Usage: npm run experiment [-- <variant>]
    Example: npm run experiment -- v3
    Results saved to tests/experiments/results/
    """
    variant = sys.argv[2] if len(sys.argv) > 2 else ""
    experiments_dir = ROOT / "tests" / "experiments"
    results_dir = experiments_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    fixture = experiments_dir / "fixtures" / "frames.json"
    if not fixture.exists():
        print("==> No fixture found. Creating snapshot first...")
        run([sys.executable, str(experiments_dir / "snapshot.py")], cwd=ROOT)

    # Copy fixtures + prompts into container
    print("==> Copying fixtures + prompts into container...")
    run(["docker", "compose", "exec", "-T", "engine",
         "mkdir", "-p", "/app/tests/experiments"], cwd=ROOT)
    run(["docker", "compose", "cp",
         str(experiments_dir / "fixtures") + "/.", "engine:/app/tests/experiments/fixtures"], cwd=ROOT)
    run(["docker", "compose", "cp",
         str(experiments_dir / "prompts") + "/.", "engine:/app/tests/experiments/prompts"], cwd=ROOT)

    # Run experiment
    print("==> Running experiment...")
    run([
        "docker", "compose", "exec", "-T", "-u", "engine", "engine",
        "uv", "run", "python", "-u", "-m", "engine.experiments.runner",
    ] + ([variant] if variant else []), cwd=ROOT)

    # Copy results out
    run(["docker", "compose", "cp",
         "engine:/data/experiment_results/.", str(results_dir)], cwd=ROOT)

    for f in sorted(results_dir.glob("*.json")):
        print(f"  {f.name}")
    print(f"==> Results in {results_dir}/")


def cmd_test_integration():
    """Run integration tests inside Docker (real LLM, real search).

    Usage: npm run test:integration
    """
    integration_dir = ROOT / "tests" / "integration"
    if not integration_dir.exists():
        print("==> No integration tests found")
        return

    # Copy test files into container
    run(["docker", "compose", "exec", "-T", "engine",
         "mkdir", "-p", "/app/tests/integration"], cwd=ROOT)
    run(["docker", "compose", "cp",
         str(integration_dir) + "/.", "engine:/app/tests/integration"], cwd=ROOT)

    # Run each test file
    results_dir = ROOT / "tests" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    integration_log = results_dir / "integration.log"

    test_files = sorted(integration_dir.glob("test_*.py"))
    failed = []
    with open(integration_log, "w") as log:
        for tf in test_files:
            print(f"==> Running {tf.name}...")
            r = subprocess.run([
                "docker", "compose", "exec", "-T", "-u", "engine", "engine",
                "uv", "run", "python", "-u", f"/app/tests/integration/{tf.name}",
            ], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            if r.returncode != 0:
                failed.append(tf.name)

    if failed:
        print(f"\n==> FAILED: {', '.join(failed)}")
        print(f"  See {integration_log}")
        sys.exit(1)
    print(f"\n==> All {len(test_files)} integration tests passed")
    print(f"  Log: {integration_log}")


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
    "watchdog": cmd_watchdog,
    "watchdog-off": cmd_watchdog_off,
    "experiment": cmd_experiment,
    "test-integration": cmd_test_integration,
}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("Commands:", ", ".join(COMMANDS))
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
