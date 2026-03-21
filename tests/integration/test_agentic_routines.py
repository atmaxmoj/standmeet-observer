"""Integration test for agentic L3 routine composition — runs inside Docker.

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
    path = RESULTS_DIR / f"routine_{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _setup_test_db():
    """Create a test schema in PostgreSQL with seed data."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from engine.storage.models import Base, Episode, Frame, PlaybookEntry

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

    # Insert episodes showing a recurring PR review workflow
    for i in range(3):
        session.add(Episode(
            summary=json.dumps({
                "summary": f"Episode {i}: Opened PR, ran CI tests, reviewed diff, addressed feedback, merged to main.",
                "method": "PR review cycle: open → CI → review → fix → merge",
                "turning_points": ["switched from squash to rebase after review feedback"],
                "avoidance": ["did not merge without CI passing"],
                "under_pressure": False,
            }),
            app_names=json.dumps(["GitHub", "Terminal", "VSCode"]),
            frame_count=60,
            started_at=f"2026-03-17T{10 + i}:00:00Z",
            ended_at=f"2026-03-17T{10 + i}:45:00Z",
            frame_id_min=i * 100 + 1,
            frame_id_max=(i + 1) * 100,
            frame_source="capture",
        ))

    # Insert playbook entries that the routine should reference
    for name, context, action in [
        ("run-ci-before-merge", "Before merging code", "Always run CI pipeline and wait for green before merging"),
        ("review-diff-before-approve", "When reviewing a PR", "Read the full diff before approving, check for edge cases"),
        ("address-feedback-before-merge", "After receiving review feedback", "Address all comments before requesting re-review"),
    ]:
        session.add(PlaybookEntry(
            name=name, context=context, action=action,
            confidence=0.7, maturity="developing", evidence="[1, 2, 3]",
        ))

    # Insert frames
    for i in range(10):
        session.add(Frame(
            timestamp=f"2026-03-17T10:{i:02d}:00Z",
            app_name="GitHub", window_name="Pull Request #42",
            text=f"Review comment {i}: looks good, minor fix needed", display_id=1,
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


def test_agentic_routines_uses_tools():
    """Full agentic routine composition — multi-turn tool loop."""
    from engine.config import Settings
    from engine.pipeline.orchestrator import run_routines

    settings = Settings()

    session, schema, pg_url = _setup_test_db()
    try:
        count = run_routines(settings, session)
        session.commit()

        from engine.storage.models import PipelineLog, Routine
        from sqlalchemy import select
        logs = session.execute(select(PipelineLog)).scalars().all()
        routines = session.execute(select(Routine)).scalars().all()

        save_result("full", {
            "routines_written": count,
            "routines": [{"name": r.name, "trigger": r.trigger, "confidence": r.confidence} for r in routines],
            "logs": [{"stage": lg.stage} for lg in logs],
        })

        assert count > 0 or len(routines) > 0, "Agent wrote 0 routines"
    finally:
        session.close()
        _cleanup(pg_url, schema)


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
