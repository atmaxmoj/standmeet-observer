"""Integration test for agentic L2 distillation — runs inside Docker.

Usage: npm run test:integration
"""

import json
import logging
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/app/src")

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s %(message)s")

RESULTS_DIR = Path("/data/test_results")


def save_result(name: str, data: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"agentic_{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _setup_test_db():
    """Create a test schema in PostgreSQL with seed data. Returns (session, schema_name)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from engine.storage.models import Base, Episode, Frame

    pg_url = os.environ.get("DATABASE_URL_SYNC", "postgresql+psycopg://observer:observer@db-test:5432/observer_test")
    schema = f"inttest_{uuid.uuid4().hex[:8]}"

    admin = create_engine(pg_url)
    with admin.connect() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
        c.commit()
    admin.dispose()

    engine = create_engine(f"{pg_url}?options=-csearch_path%3D{schema}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    episodes_data = [
        {
            "summary": "Debugging a failing test: checked logs first, found the root cause in a config mismatch, fixed the config file, re-ran tests until green.",
            "method": "logs → root cause → fix → verify",
            "turning_points": ["initially tried restarting the service, then switched to reading logs"],
            "avoidance": ["did not use print debugging, used structured logs instead"],
            "under_pressure": False,
            "apps": ["VSCode", "Terminal", "Chrome"],
        },
        {
            "summary": "Code review workflow: opened PR, ran CI, reviewed diff line by line, left comments on edge cases, requested changes, approved after fixes.",
            "method": "PR → CI → review → feedback → approve",
            "turning_points": ["caught a subtle bug during review that tests missed"],
            "avoidance": ["did not approve without running CI first"],
            "under_pressure": False,
            "apps": ["GitHub", "VSCode"],
        },
        {
            "summary": "Refactoring a module: wrote characterization tests first, then restructured code in small steps, running tests after each change to ensure no regression.",
            "method": "test first → small refactor steps → verify after each",
            "turning_points": ["reverted one change that broke an edge case, took a smaller step instead"],
            "avoidance": ["did not refactor without test coverage"],
            "under_pressure": False,
            "apps": ["VSCode", "Terminal"],
        },
    ]
    for i, ep in enumerate(episodes_data):
        session.add(Episode(
            summary=json.dumps({
                "summary": ep["summary"], "method": ep["method"],
                "turning_points": ep["turning_points"], "avoidance": ep["avoidance"],
                "under_pressure": ep["under_pressure"],
            }),
            app_names=json.dumps(ep["apps"]),
            frame_count=50,
            started_at=f"2026-03-17T1{i}:00:00Z",
            ended_at=f"2026-03-17T1{i}:30:00Z",
            frame_id_min=i * 100 + 1,
            frame_id_max=(i + 1) * 100,
            frame_source="capture",
        ))
    for i in range(10):
        session.add(Frame(
            timestamp=f"2026-03-17T10:{i:02d}:00Z",
            app_name="VSCode", window_name="editor.py",
            text=f"def function_{i}(): pass", display_id=1,
        ))
    session.commit()
    return session, schema, pg_url


def _cleanup(pg_url: str, schema: str):
    from sqlalchemy import create_engine, text
    engine = create_engine(pg_url)
    with engine.connect() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        c.commit()
    engine.dispose()


def test_agentic_distill_uses_tools():
    """Full agentic distill — multi-turn tool loop."""
    from engine.config import Settings
    from engine.pipeline.orchestrator import run_distill

    settings = Settings()

    session, schema, pg_url = _setup_test_db()
    try:
        count = run_distill(settings, session)
        session.commit()

        from engine.storage.models import PipelineLog, PlaybookEntry
        from sqlalchemy import select
        logs = session.execute(select(PipelineLog)).scalars().all()
        entries = session.execute(select(PlaybookEntry)).scalars().all()

        save_result("distill_full", {
            "entries_written": count,
            "playbook_entries": [{"name": e.name, "context": e.context, "confidence": e.confidence} for e in entries],
            "logs": [{"stage": lg.stage} for lg in logs],
        })

        assert count > 0 or len(entries) > 0, "Agent wrote 0 entries"
    finally:
        session.close()
        _cleanup(pg_url, schema)


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
