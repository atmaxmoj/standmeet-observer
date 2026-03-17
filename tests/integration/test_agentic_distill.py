"""Integration test for agentic L2 distillation — runs inside Docker.

Usage: npm run test:integration
"""

import json
import os
import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, "/app/src")

RESULTS_DIR = Path("/data/test_results")


def save_result(name: str, data: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"agentic_{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _setup_test_db(tmp_dir: str) -> sqlite3.Connection:
    from engine.infra.db import SCHEMA
    conn = sqlite3.connect(f"{tmp_dir}/test.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for i in range(3):
        summary = json.dumps({
            "summary": f"Episode {i}: Edited code, ran tests, committed.",
            "method": "edit-test-commit cycle",
            "turning_points": ["switched from manual to automated testing"],
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
    for i in range(10):
        conn.execute(
            "INSERT INTO frames (timestamp, app_name, window_name, text, display_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"2026-03-17T10:{i:02d}:00Z", "VSCode", "editor.py",
             f"def function_{i}(): pass", 1),
        )
    conn.commit()
    return conn


def test_oauth_direct_with_distill_tools():
    """Test OAuth API with the actual distill tools — isolate the 400 error."""
    import anthropic
    from engine.pipeline.stages.distill_tools import make_distill_tools

    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not token:
        print("  SKIP  no token")
        return

    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_test_db(tmp)
        tools = make_distill_tools(conn)

        # Build API tools same way as complete_with_tools
        api_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]

        client = anthropic.Anthropic(
            api_key=None,
            auth_token=token,
            default_headers={
                "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
                "user-agent": "claude-cli/2.1.75",
                "x-app": "cli",
            },
        )

        save_result("tools_sent", {"tools": api_tools})

        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                messages=[{"role": "user", "content": "List all playbook entries."}],
                tools=api_tools,
            )
            content = [{"type": b.type, "name": getattr(b, "name", None)}
                       for b in resp.content]
            save_result("success", {
                "stop_reason": resp.stop_reason,
                "content": content,
            })
            print(f"  Stop reason: {resp.stop_reason}, Content: {content}")
            conn.close()
        except Exception as e:
            save_result("error", {
                "error": str(e),
                "type": type(e).__name__,
                "traceback": traceback.format_exc(),
            })
            conn.close()
            raise


def test_agentic_distill_uses_tools():
    """Full agentic distill — multi-turn tool loop."""
    from engine.config import Settings
    from engine.infra.llm import create_client
    from engine.pipeline.orchestrator import run_distill

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
            count = run_distill(llm, conn, agentic=True)
            conn.commit()
        except Exception as e:
            save_result("distill_error", {
                "error": str(e),
                "type": type(e).__name__,
                "traceback": traceback.format_exc(),
            })
            conn.close()
            raise

        logs = conn.execute(
            "SELECT * FROM pipeline_logs WHERE stage LIKE 'distill%' ORDER BY id",
        ).fetchall()
        entries = conn.execute("SELECT * FROM playbook_entries").fetchall()

        save_result("distill_full", {
            "entries_written": count,
            "tool_calls": len([l for l in logs if l["stage"] == "distill_agentic"]),
            "playbook_entries": [dict(e) for e in entries],
            "logs": [{"stage": l["stage"], "prompt": l["prompt"][:200]} for l in logs],
        })
        conn.close()

    assert count > 0 or len(entries) > 0, "Agent wrote 0 entries"


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [test_oauth_direct_with_distill_tools, test_agentic_distill_uses_tools]
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
