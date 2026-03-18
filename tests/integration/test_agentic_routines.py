"""Integration test for agentic L3 routine composition — runs inside Docker.

Usage: npm run test:integration
"""

import json
import logging
import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, "/app/src")

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s %(message)s")

RESULTS_DIR = Path("/data/test_results")


def save_result(name: str, data: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"routine_{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _setup_test_db(tmp_dir: str) -> sqlite3.Connection:
    from engine.storage.db import SCHEMA
    conn = sqlite3.connect(f"{tmp_dir}/test.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    # Insert episodes that show a recurring multi-step workflow
    for i in range(3):
        summary = json.dumps({
            "summary": f"Episode {i}: Opened PR, ran CI tests, reviewed diff, addressed feedback, merged to main.",
            "method": "PR review cycle: open → CI → review → fix → merge",
            "turning_points": ["switched from squash to rebase after review feedback"],
            "avoidance": ["did not merge without CI passing"],
            "under_pressure": False,
        })
        conn.execute(
            "INSERT INTO episodes (summary, app_names, frame_count, started_at, ended_at, "
            "frame_id_min, frame_id_max, frame_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (summary, '["GitHub", "Terminal", "VSCode"]', 60,
             f"2026-03-17T{10 + i}:00:00Z", f"2026-03-17T{10 + i}:45:00Z",
             i * 100 + 1, (i + 1) * 100, "capture"),
        )

    # Insert playbook entries that the routine should reference
    for name, context, action in [
        ("run-ci-before-merge", "Before merging code", "Always run CI pipeline and wait for green before merging"),
        ("review-diff-before-approve", "When reviewing a PR", "Read the full diff before approving, check for edge cases"),
        ("address-feedback-before-merge", "After receiving review feedback", "Address all comments before requesting re-review"),
    ]:
        conn.execute(
            "INSERT INTO playbook_entries (name, context, action, confidence, maturity, evidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, context, action, 0.7, "developing", "[1, 2, 3]"),
        )

    # Insert frames for episode 1
    for i in range(10):
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, window_name, text, display_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"2026-03-17T10:{i:02d}:00Z", "GitHub", "Pull Request #42",
             f"Review comment {i}: looks good, minor fix needed", 1),
        )
    conn.commit()
    return conn


def test_agentic_routines_uses_tools():
    """Full agentic routine composition — multi-turn tool loop."""
    from engine.config import Settings
    from engine.llm import create_client
    from engine.pipeline.orchestrator import run_routines

    settings = Settings()
    llm = create_client(
        api_key=settings.anthropic_api_key,
        auth_token=settings.claude_code_oauth_token,
        openai_api_key=settings.openai_api_key,
        openai_base_url=settings.openai_base_url,
    )

    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_test_db(tmp)
        try:
            count = run_routines(llm, conn, agentic=True)
            conn.commit()
        except Exception as e:
            save_result("error", {
                "error": str(e),
                "type": type(e).__name__,
                "traceback": traceback.format_exc(),
            })
            conn.close()
            raise

        logs = conn.execute(
            "SELECT * FROM pipeline_logs WHERE stage LIKE 'routine%' ORDER BY id",
        ).fetchall()
        routines = conn.execute("SELECT * FROM routines").fetchall()

        save_result("full", {
            "routines_written": count,
            "tool_calls": len([row for row in logs if row["stage"] == "compose_agentic"]),
            "routines": [dict(r) for r in routines],
            "logs": [{"stage": row["stage"], "prompt": row["prompt"][:200]} for row in logs],
        })
        conn.close()

    assert count > 0 or len(routines) > 0, "Agent wrote 0 routines"


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [test_agentic_routines_uses_tools]
    for test in tests:
        name = test.__name__
        try:
            test()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    print(f"Results saved to {RESULTS_DIR}/")
    sys.exit(1 if failed else 0)
