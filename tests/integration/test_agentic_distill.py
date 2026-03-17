"""Integration test for agentic L2 distillation — runs inside Docker.

Verifies that the LLM can use tools to investigate episodes and write playbook entries.
Results saved to /data/test_results/.

Usage: npm run test:integration
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")

RESULTS_DIR = Path("/data/test_results")


def save_result(name: str, data: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"agentic_distill_{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _setup_test_db(tmp_dir: str) -> sqlite3.Connection:
    """Create a test DB with schema and seed data."""
    from engine.infra.db import SCHEMA
    conn = sqlite3.connect(f"{tmp_dir}/test.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    # Seed episodes
    for i in range(3):
        summary = json.dumps({
            "summary": f"Episode {i}: Edited code in editor, ran tests, committed changes.",
            "method": "edit-test-commit cycle",
            "turning_points": ["switched from manual testing to automated"],
            "avoidance": ["did not use debugger"],
            "under_pressure": False,
        })
        conn.execute(
            "INSERT INTO episodes (summary, app_names, frame_count, started_at, ended_at, "
            "frame_id_min, frame_id_max, frame_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (summary, '["VSCode", "Terminal"]', 50,
             f"2026-03-17T1{i}:00:00Z", f"2026-03-17T1{i}:30:00Z",
             i * 100 + 1, (i + 1) * 100, "capture"),
        )

    # Seed some frames for episodes to reference
    for i in range(10):
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, window_name, text, display_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"2026-03-17T10:{i:02d}:00Z", "VSCode", "editor.py",
             f"def function_{i}(): pass  # editing code", 1),
        )

    conn.commit()
    return conn


def test_agentic_distill_uses_tools():
    """The agent should call at least one tool and write at least one entry."""
    import tempfile
    from engine.config import Settings
    from engine.infra.llm import create_client

    settings = Settings()
    llm = create_client(
        api_key=settings.anthropic_api_key,
        auth_token=settings.claude_code_oauth_token,
        openai_api_key=settings.openai_api_key,
        openai_base_url=settings.openai_base_url,
    )

    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_test_db(tmp)

        from engine.pipeline.orchestrator import run_distill
        count = run_distill(llm, conn, agentic=True)
        conn.commit()

        # Check pipeline logs for tool calls
        logs = conn.execute(
            "SELECT * FROM pipeline_logs WHERE stage = 'distill_agentic' ORDER BY id",
        ).fetchall()
        tool_logs = [dict(l) for l in logs]

        # Check playbook entries
        entries = conn.execute("SELECT * FROM playbook_entries").fetchall()
        entry_list = [dict(e) for e in entries]

        save_result("full", {
            "entries_written": count,
            "tool_calls": len(tool_logs),
            "tool_names": [json.loads(l["prompt"]).get("tool", "?") for l in tool_logs if l["prompt"]],
            "playbook_entries": entry_list,
        })

        conn.close()

    assert len(tool_logs) > 0, f"Agent made 0 tool calls — not agentic. Logs: {tool_logs}"
    assert count > 0 or len(entry_list) > 0, "Agent wrote 0 playbook entries"
    print(f"  Tool calls: {len(tool_logs)}, Entries: {len(entry_list)}")


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [test_agentic_distill_uses_tools]
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
