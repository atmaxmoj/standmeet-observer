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


def daemon_start_source(name: str, source_dir: Path):
    """Start a source plugin as an independent daemon process."""
    pid = daemon_running(f"source-{name}")
    if pid:
        print(f"  source/{name} already running (pid {pid})")
        return

    PID_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = _log_file(f"source-{name}")

    print(f"  Starting source/{name}...")
    with open(log, "w") as lf:
        kwargs = dict(
            cwd=source_dir,
            stdout=lf, stderr=lf,
        )
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        p = subprocess.Popen(
            ["uv", "run", "python", "-m", "source_framework", "."],
            **kwargs,
        )

    _pid_file(f"source-{name}").write_text(str(p.pid))
    print(f"  source/{name} started (pid {p.pid}) → {log}")


def _iter_source_manifests():
    """Yield (source_name, source_dir, manifest) for each builtin source with a manifest."""
    import json
    sources_dir = ROOT / "sources" / "builtin"
    if not sources_dir.is_dir():
        return
    for source_dir in sorted(sources_dir.iterdir()):
        manifest_file = source_dir / "manifest.json"
        if manifest_file.exists():
            manifest = json.loads(manifest_file.read_text())
            yield manifest["name"], source_dir, manifest


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

    print("==> Installing source framework...")
    run(["uv", "sync"], cwd=ROOT / "sources" / "framework")

    print("==> Building Docker images...")
    run(["docker", "compose", "build"], cwd=ROOT)

    print("\n==> Setup complete! Run: npm start")


def cmd_start():
    print("==> Starting observer...")
    check_prereqs()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("==> Starting source plugins...")
    for source_name, source_dir, manifest in _iter_source_manifests():
        platforms = manifest.get("platform", [])
        if platforms and sys.platform not in platforms:
            print(f"  Skipping {source_name} (platform {sys.platform} not in {platforms})")
            continue
        daemon_start_source(source_name, source_dir)

    print("==> Building + starting engine + web containers...")
    run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT)

    print()
    print("  Dashboard:  http://localhost:5174")
    print("  API:        http://localhost:5001")


def cmd_stop():
    print("==> Stopping observer...")
    # Stop source plugin daemons
    for source_name, _source_dir, _manifest in _iter_source_manifests():
        daemon_stop(f"source-{source_name}")
    run(["docker", "compose", "down"], cwd=ROOT)
    print("==> Stopped")


def cmd_status():
    # Source plugins
    for source_name, _source_dir, _manifest in _iter_source_manifests():
        pid = daemon_running(f"source-{source_name}")
        status = f"RUNNING (pid {pid})" if pid else "NOT RUNNING"
        print(f"  source/{source_name}: {status}")

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


def _compose(compose_test, *args):
    """Run docker compose with the test project."""
    return run(["docker", "compose", "-p", "observer-test", "-f", compose_test] + list(args), cwd=ROOT)


def _test_unit(compose_test, results_dir):
    """Layer 1: unit tests (no DB, pure logic)."""
    results = []
    print("==> [1/4] Source framework unit tests (Docker)...")
    sources_log = results_dir / "sources.log"
    with open(sources_log, "w") as log:
        r = subprocess.run(
            ["docker", "compose", "-p", "observer-test", "-f", compose_test, "run", "--rm", "pytest-sources"],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
    results.append(("sources", r.returncode))
    if r.returncode != 0:
        print(f"  See {sources_log}")

    print("\n==> [1/4] Engine unit tests (Docker, no DB)...")
    unit_log = results_dir / "unit.log"
    with open(unit_log, "w") as log:
        r = subprocess.run(
            ["docker", "compose", "-p", "observer-test", "-f", compose_test, "run", "--rm", "pytest-unit"],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
    results.append(("unit", r.returncode))
    if r.returncode != 0:
        print(f"  See {unit_log}")

    print("\n==> [1/4] Web unit tests (Docker, vitest)...")
    vitest_log = results_dir / "vitest.log"
    with open(vitest_log, "w") as log:
        r = subprocess.run(
            ["docker", "compose", "-p", "observer-test", "-f", compose_test, "run", "--rm", "vitest"],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
    results.append(("vitest", r.returncode))
    if r.returncode != 0:
        print(f"  See {vitest_log}")
    return results


def _test_db(compose_test, results_dir):
    """Layer 2: DB integration tests (needs PostgreSQL)."""
    results = []
    print("\n==> [2/4] Engine DB tests (Docker + PostgreSQL)...")
    _compose(compose_test, "up", "-d", "--build", "--wait", "db-test")
    engine_log = results_dir / "engine.log"
    with open(engine_log, "w") as log:
        r = subprocess.run(
            ["docker", "compose", "-p", "observer-test", "-f", compose_test, "run", "--rm", "pytest"],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
    results.append(("engine-db", r.returncode))
    if r.returncode != 0:
        print(f"  See {engine_log}")
    return results


def _test_integration(compose_test, results_dir):
    """Layer 3: integration tests (real LLM)."""
    integration_dir = ROOT / "tests" / "integration"
    test_files = sorted(integration_dir.glob("test_*.py")) if integration_dir.exists() else []
    if not test_files:
        print("\n==> [3/4] No integration tests found, skipping")
        return []

    print("\n==> [3/4] Integration tests (Docker, real LLM)...")
    _compose(compose_test, "up", "-d", "--build", "--wait", "engine-test")
    _compose(compose_test, "exec", "-T", "engine-test", "mkdir", "-p", "/app/tests/integration")
    _compose(compose_test, "cp", str(integration_dir) + "/.", "engine-test:/app/tests/integration")

    integration_log = results_dir / "integration.log"
    failed_tests = []
    with open(integration_log, "w") as log:
        for tf in test_files:
            print(f"  Running {tf.name}...")
            r = subprocess.run(
                ["docker", "compose", "-p", "observer-test", "-f", compose_test,
                 "exec", "-T", "-u", "engine", "engine-test",
                 "uv", "run", "python", "-u", f"/app/tests/integration/{tf.name}"],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            )
            if r.returncode != 0:
                failed_tests.append(tf.name)

    _compose(compose_test, "cp", "engine-test:/data/test_results/.", str(results_dir / "integration"))
    if failed_tests:
        print(f"  Failed: {', '.join(failed_tests)}")
        print(f"  See {integration_log}")
    return [("integration", 1 if failed_tests else 0)]


def _test_e2e(compose_test, results_dir):
    """Layer 4: Playwright e2e (real LLM, full pipeline)."""
    print("\n==> [4/4] Playwright e2e tests (Docker, real LLM)...")
    _compose(compose_test, "build", "playwright")
    _compose(compose_test, "up", "-d", "--build", "--wait", "engine-test")
    web_log = results_dir / "web.log"
    with open(web_log, "w") as log:
        r = subprocess.run(
            ["docker", "compose", "-p", "observer-test", "-f", compose_test, "run", "--rm", "playwright"],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
    _compose(compose_test, "cp", "engine-test:/data/.", str(results_dir / "web-data"))
    # Always dump engine logs (before down -v destroys containers)
    engine_e2e_log = results_dir / "engine-e2e.log"
    with open(engine_e2e_log, "w") as elog:
        subprocess.run(
            ["docker", "compose", "-p", "observer-test", "-f", compose_test, "logs", "engine-test"],
            cwd=ROOT, stdout=elog, stderr=subprocess.STDOUT,
        )
    if r.returncode != 0:
        print(f"  See {web_log}")
    print(f"  Engine logs: {engine_e2e_log}")
    return [("e2e", r.returncode)]


def cmd_test():
    """Run tests. Usage: npm test [-- <suite>]
    Suites: unit, db, integration, e2e, all (default: all)
      unit:        Pure logic tests, no DB (sources + engine unit)
      db:          Engine tests that need PostgreSQL
      integration: Real LLM tests
      e2e:         Playwright browser tests
    """
    suite = sys.argv[2] if len(sys.argv) > 2 else "all"
    compose_test = str(ROOT / "docker-compose.test.yml")
    results_dir = ROOT / "tests" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    print("==> Running code checks...")
    for name, cmd, cwd in [
        ("ruff", ["uv", "run", "ruff", "check", "src/", "tests/", "tests_unit/", "cli.py"], ROOT),
        ("tsc", ["npx", "tsc", "--noEmit"], ROOT / "web"),
        ("eslint", ["npx", "eslint", "src/", "--max-warnings", "0"], ROOT / "web"),
        ("knip", ["npx", "knip"], ROOT / "web"),
    ]:
        if run(cmd, cwd=cwd).returncode != 0:
            sys.exit(f"\n==> CODE CHECK FAILED: {name}")
    print("==> All code checks passed\n")

    results = []
    if suite in ("unit", "all"):
        results.extend(_test_unit(compose_test, results_dir))
    if suite in ("db", "all"):
        results.extend(_test_db(compose_test, results_dir))
    if suite in ("integration", "all"):
        results.extend(_test_integration(compose_test, results_dir))
    if suite in ("e2e", "all"):
        results.extend(_test_e2e(compose_test, results_dir))

    _compose(compose_test, "down", "-v")

    if not results:
        sys.exit(f"Unknown suite: {suite}. Available: unit, db, integration, e2e, all")

    print("\n==> Results:")
    for name, rc in results:
        print(f"  {name}: {'PASSED' if rc == 0 else 'FAILED'}")
    failed = [name for name, rc in results if rc != 0]
    if failed:
        sys.exit(f"\n==> FAILED: {', '.join(failed)}")
    print("\n==> ALL TESTS PASSED")

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

    # Copy fixtures + prompts + runner into container
    print("==> Copying experiments into container...")
    run(["docker", "compose", "exec", "-T", "engine",
         "mkdir", "-p", "/app/tests/experiments", "/app/experiments"], cwd=ROOT)
    run(["docker", "compose", "cp",
         str(experiments_dir / "fixtures") + "/.", "engine:/app/tests/experiments/fixtures"], cwd=ROOT)
    run(["docker", "compose", "cp",
         str(experiments_dir / "prompts") + "/.", "engine:/app/tests/experiments/prompts"], cwd=ROOT)
    run(["docker", "compose", "cp",
         str(ROOT / "experiments") + "/.", "engine:/app/experiments"], cwd=ROOT)

    # Run experiment
    print("==> Running experiment...")
    run([
        "docker", "compose", "exec", "-T", "-u", "engine", "engine",
        "uv", "run", "python", "-u", "/app/experiments/runner.py",
    ] + ([variant] if variant else []), cwd=ROOT)

    # Copy results out
    run(["docker", "compose", "cp",
         "engine:/data/experiment_results/.", str(results_dir)], cwd=ROOT)

    for f in sorted(results_dir.glob("*.json")):
        print(f"  {f.name}")
    print(f"==> Results in {results_dir}/")


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
    "experiment": cmd_experiment,
}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("Commands:", ", ".join(COMMANDS))
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
