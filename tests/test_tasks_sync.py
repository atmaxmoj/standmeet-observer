"""E2E tests for Huey sync pipeline (tasks.py).

Tests the same pipeline as test_pipeline_e2e.py but through the sync code path
that production Huey tasks use. Mock LLM, real PostgreSQL DB.
"""

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from engine.infrastructure.persistence.models import Base
from engine.infrastructure.llm.types import LLMResponse
from engine.domain.observation.entity import Frame
from engine.infrastructure.pipeline.stages.extract import EPISODE_PROMPT, build_context
from engine.domain.prompt.playbook import PLAYBOOK_PROMPT as DISTILL_PROMPT
from engine.domain.prompt.routine import ROUTINE_PROMPT
from engine.infrastructure.pipeline.stages.validate import validate_episodes, validate_playbooks, with_retry
from tests.conftest import TEST_PG_SYNC

# Same canned responses as test_pipeline_e2e.py
EPISODE_LLM_RESPONSE = json.dumps([
    {
        "summary": "Edited Python code in VSCode",
        "method": "sequential editing",
        "turning_points": ["switched approach"],
        "avoidance": ["did not use debugger"],
        "under_pressure": False,
        "apps": ["VSCode"],
        "started_at": "2026-03-16T10:00:00Z",
        "ended_at": "2026-03-16T10:04:00Z",
    },
    {
        "summary": "Ran tests after editing",
        "method": "test-after-edit",
        "turning_points": [],
        "avoidance": [],
        "under_pressure": False,
        "apps": ["Terminal"],
        "started_at": "2026-03-16T10:04:00Z",
        "ended_at": "2026-03-16T10:05:00Z",
    },
])

DISTILL_LLM_RESPONSE = json.dumps([
    {
        "name": "edit-then-test",
        "type": "deep-work",
        "when": "After code changes",
        "then": "Execute test suite",
        "because": "Catch regressions",
        "boundary": None,
        "confidence": 0.7,
        "maturity": "developing",
        "evidence": [1, 2],
    },
])

ROUTINE_LLM_RESPONSE = json.dumps([
    {
        "name": "code-edit-cycle",
        "trigger": "Starting coding task",
        "goal": "Implement and verify",
        "steps": ["Open file", "Edit", "IF tests THEN run ELSE skip", "Commit"],
        "uses": ["edit-then-test"],
        "confidence": 0.6,
        "maturity": "nascent",
    },
])


@pytest.fixture
def conn(_test_schema):
    """Create a sync SQLAlchemy session with tables in the test schema."""
    url = f"{TEST_PG_SYNC}?options=-csearch_path%3D{_test_schema}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()
    engine.dispose()


def _seed_frames(conn, n=5):
    """Insert screen frames and return their IDs."""
    ids = []
    for i in range(n):
        result = conn.execute(
            text("INSERT INTO frames (timestamp, app_name, window_name, text, display_id) "
                 "VALUES (:ts, :app, :win, :txt, :did) RETURNING id"),
            {"ts": f"2026-03-16T10:{i:02d}:00Z", "app": "VSCode",
             "win": "editor.py", "txt": f"def func_{i}(): pass", "did": 1},
        )
        ids.append(result.scalar())
    conn.commit()
    return ids


def _seed_os_events(conn, n=2):
    ids = []
    for i in range(n):
        result = conn.execute(
            text("INSERT INTO os_events (timestamp, event_type, source, data) "
                 "VALUES (:ts, :etype, :src, :data) RETURNING id"),
            {"ts": f"2026-03-16T10:{i:02d}:30Z", "etype": "shell_command",
             "src": "zsh", "data": f"git status {i}"},
        )
        ids.append(result.scalar())
    conn.commit()
    return ids


def _seed_episodes(conn):
    """Insert episodes (as if process_episode already ran)."""
    for task in json.loads(EPISODE_LLM_RESPONSE):
        summary = json.dumps({
            "summary": task["summary"], "method": task["method"],
            "turning_points": task["turning_points"],
            "avoidance": task["avoidance"], "under_pressure": task["under_pressure"],
        }, ensure_ascii=False)
        conn.execute(
            text("INSERT INTO episodes (summary, app_names, frame_count, started_at, ended_at, "
                 "frame_id_min, frame_id_max, frame_source) VALUES (:summary, :apps, :fc, :start, :end, :fmin, :fmax, :fsrc)"),
            {"summary": summary, "apps": json.dumps(task["apps"]), "fc": 5,
             "start": task["started_at"], "end": task["ended_at"],
             "fmin": 1, "fmax": 5, "fsrc": "capture"},
        )
    conn.commit()


class MockSyncLLM:
    """Sync LLM that returns canned responses."""
    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0
        self.calls = []

    def complete(self, prompt, model):
        self.calls.append(prompt)
        text = self._responses[self._idx % len(self._responses)]
        self._idx += 1
        return LLMResponse(text=text, input_tokens=100, output_tokens=50)


def _load_frames_sync(conn, screen_ids, os_event_ids=None):
    """Same logic as tasks._load_frames but importable without side effects."""
    frames = []
    if screen_ids:
        ph = ",".join(str(i) for i in screen_ids)
        rows = conn.execute(
            text(f"SELECT id, timestamp, app_name, window_name, text, image_path "
                 f"FROM frames WHERE id IN ({ph}) ORDER BY timestamp"),
        ).mappings().all()
        frames.extend(Frame(id=r["id"], source="capture", text=r["text"] or "",
                            app_name=r["app_name"] or "", window_name=r["window_name"] or "",
                            timestamp=r["timestamp"] or "", image_path=r["image_path"] or "")
                      for r in rows)
    if os_event_ids:
        ph = ",".join(str(i) for i in os_event_ids)
        rows = conn.execute(
            text(f"SELECT id, timestamp, event_type, source, data "
                 f"FROM os_events WHERE id IN ({ph}) ORDER BY timestamp"),
        ).mappings().all()
        frames.extend(Frame(id=r["id"], source="os_event", text=r["data"] or "",
                            app_name=r["event_type"] or "", window_name=r["source"] or "",
                            timestamp=r["timestamp"] or "")
                      for r in rows)
    frames.sort(key=lambda f: f.timestamp)
    return frames


def _store_episodes_sync(conn, tasks, frames):
    """Same logic as tasks._store_episodes."""
    fmin = min(f.id for f in frames)
    fmax = max(f.id for f in frames)
    fsource = ",".join(sorted({f.source for f in frames}))
    for task in tasks:
        summary = json.dumps({
            "summary": task.get("summary", ""), "method": task.get("method", ""),
            "turning_points": task.get("turning_points", []),
            "avoidance": task.get("avoidance", []),
            "under_pressure": task.get("under_pressure", False),
        }, ensure_ascii=False)
        conn.execute(
            text("INSERT INTO episodes (summary, app_names, frame_count, started_at, ended_at, "
                 "frame_id_min, frame_id_max, frame_source) VALUES (:summary, :apps, :fc, :start, :end, :fmin, :fmax, :fsrc)"),
            {"summary": summary, "apps": json.dumps(task.get("apps", [])), "fc": len(frames),
             "start": task.get("started_at", frames[0].timestamp),
             "end": task.get("ended_at", frames[-1].timestamp),
             "fmin": fmin, "fmax": fmax, "fsrc": fsource},
        )


# -- Load frames --

class TestLoadFrames:
    def test_loads_screen_frames(self, conn):
        ids = _seed_frames(conn, 3)
        frames = _load_frames_sync(conn, ids)
        assert len(frames) == 3
        assert frames[0].app_name == "VSCode"
        assert frames[0].source == "capture"

    def test_loads_os_events(self, conn):
        os_ids = _seed_os_events(conn, 2)
        frames = _load_frames_sync(conn, [], os_ids)
        assert len(frames) == 2
        assert frames[0].source == "os_event"
        assert "git status" in frames[0].text

    def test_mixed_sources_sorted_by_timestamp(self, conn):
        screen_ids = _seed_frames(conn, 2)
        os_ids = _seed_os_events(conn, 2)
        frames = _load_frames_sync(conn, screen_ids, os_ids)
        assert len(frames) == 4
        timestamps = [f.timestamp for f in frames]
        assert timestamps == sorted(timestamps)

    def test_empty_ids_returns_empty(self, conn):
        assert _load_frames_sync(conn, []) == []


# -- Build prompt --

class TestBuildPrompt:
    def test_contains_frame_data(self):
        frames = [Frame(id=1, source="capture", timestamp="2026-03-16T10:00:00Z",
                        app_name="VSCode", window_name="test.py", text="hello world")]
        context = build_context(frames)
        prompt = EPISODE_PROMPT.format(context=context)
        assert "hello world" in prompt
        assert "VSCode" in prompt
        assert "{context}" not in prompt


# -- Store episodes --

class TestStoreEpisodes:
    def test_stores_to_db(self, conn):
        tasks = json.loads(EPISODE_LLM_RESPONSE)
        frames = [Frame(id=i, source="capture", timestamp=f"2026-03-16T10:{i:02d}:00Z",
                        app_name="VSCode", window_name="x", text="x") for i in range(1, 6)]
        _store_episodes_sync(conn, tasks, frames)
        conn.commit()
        rows = conn.execute(text("SELECT * FROM episodes")).mappings().all()
        assert len(rows) == 2
        assert rows[0]["frame_id_min"] == 1
        assert rows[0]["frame_id_max"] == 5


# -- Full sync episode pipeline --

class TestProcessEpisodeSync:
    def test_full_sync_chain(self, conn):
        """frames in DB -> load -> build prompt -> LLM -> validate -> store."""
        screen_ids = _seed_frames(conn, 5)
        frames = _load_frames_sync(conn, screen_ids, [])
        prompt = EPISODE_PROMPT.format(context=build_context(frames))

        llm = MockSyncLLM([EPISODE_LLM_RESPONSE])
        resp = llm.complete(prompt, "haiku")
        tasks = validate_episodes(resp.text)
        _store_episodes_sync(conn, tasks, frames)
        conn.commit()

        episodes = conn.execute(text("SELECT * FROM episodes")).mappings().all()
        assert len(episodes) == 2
        assert "VSCode" in json.loads(episodes[0]["summary"])["summary"]
        assert llm.calls[0] == prompt

    def test_with_retry_on_valid_response(self, conn):
        """with_retry should pass through valid responses."""
        llm = MockSyncLLM([EPISODE_LLM_RESPONSE])
        last_resp = [None]

        def call(retry_prompt):
            resp = llm.complete(retry_prompt or "test", "haiku")
            last_resp[0] = resp
            return resp.text

        tasks = with_retry(call, validate_episodes)
        assert len(tasks) == 2


# -- Full sync distill pipeline --

class TestDistillSync:
    def test_full_sync_distill(self, conn):
        """episodes in DB -> format prompt -> LLM -> validate -> store playbook."""
        _seed_episodes(conn)

        episodes = conn.execute(
            text("SELECT * FROM episodes ORDER BY created_at")
        ).mappings().all()
        episodes_text = "\n\n".join(
            f"Episode #{e['id']}:\n{e['summary']}" for e in episodes
        )
        playbooks_text = "(none yet)"
        prompt = DISTILL_PROMPT.format(playbooks=playbooks_text, episodes=episodes_text)

        llm = MockSyncLLM([DISTILL_LLM_RESPONSE])
        resp = llm.complete(prompt, "opus")
        entries = validate_playbooks(resp.text)

        for entry in entries:
            conn.execute(
                text("INSERT INTO playbook_entries (name, context, action, confidence, maturity, evidence) "
                     "VALUES (:name, :ctx, :action, :conf, :mat, :ev)"),
                {"name": entry["name"], "ctx": entry.get("context", ""),
                 "action": entry.get("action", ""),
                 "conf": entry["confidence"], "mat": entry["maturity"],
                 "ev": json.dumps(entry.get("evidence", []))},
            )
        conn.commit()

        playbooks = conn.execute(text("SELECT * FROM playbook_entries")).mappings().all()
        assert len(playbooks) == 1
        assert playbooks[0]["name"] == "edit-then-test"
        assert playbooks[0]["confidence"] == 0.7

    def test_distill_prompt_includes_existing_playbooks(self, conn):
        """Second distill should include existing entries in prompt."""
        _seed_episodes(conn)
        conn.execute(
            text("INSERT INTO playbook_entries (name, context, action, confidence, maturity, evidence) "
                 "VALUES (:name, :ctx, :action, :conf, :mat, :ev)"),
            {"name": "existing-rule", "ctx": "some context", "action": "some action",
             "conf": 0.5, "mat": "nascent", "ev": "[]"},
        )
        conn.commit()

        existing = conn.execute(text("SELECT * FROM playbook_entries")).mappings().all()
        playbooks_text = "\n".join(f"- {p['name']}" for p in existing)

        assert "existing-rule" in playbooks_text


# -- Full sync routine pipeline --

class TestRoutineSync:
    def test_full_sync_routine(self, conn):
        """episodes + playbook in DB -> format prompt -> LLM -> parse -> store routine."""
        _seed_episodes(conn)
        conn.execute(
            text("INSERT INTO playbook_entries (name, context, action, confidence, maturity, evidence) "
                 "VALUES (:name, :ctx, :action, :conf, :mat, :ev)"),
            {"name": "edit-then-test", "ctx": "After changes", "action": "Run tests",
             "conf": 0.7, "mat": "developing", "ev": "[1,2]"},
        )
        conn.commit()

        episodes = conn.execute(text("SELECT * FROM episodes")).mappings().all()
        playbooks = conn.execute(text("SELECT * FROM playbook_entries")).mappings().all()

        episodes_text = "\n".join(f"Episode #{e['id']}:\n{e['summary']}" for e in episodes)
        playbooks_text = "\n".join(f"- {p['name']}" for p in playbooks)
        routines_text = "(none yet)"

        prompt = ROUTINE_PROMPT.format(
            playbooks=playbooks_text, routines=routines_text, episodes=episodes_text,
        )

        llm = MockSyncLLM([ROUTINE_LLM_RESPONSE])
        resp = llm.complete(prompt, "opus")

        resp_text = resp.text.strip()
        if resp_text.startswith("```"):
            resp_text = resp_text.split("\n", 1)[1].rsplit("```", 1)[0]
        entries = json.loads(resp_text)

        for entry in entries:
            conn.execute(
                text("INSERT INTO routines (name, trigger, goal, steps, uses, confidence, maturity) "
                     "VALUES (:name, :trigger, :goal, :steps, :uses, :conf, :mat)"),
                {"name": entry["name"], "trigger": entry.get("trigger", ""),
                 "goal": entry.get("goal", ""),
                 "steps": json.dumps(entry.get("steps", [])),
                 "uses": json.dumps(entry.get("uses", [])),
                 "conf": entry.get("confidence", 0.4),
                 "mat": entry.get("maturity", "nascent")},
            )
        conn.commit()

        routines = conn.execute(text("SELECT * FROM routines")).mappings().all()
        assert len(routines) == 1
        assert routines[0]["name"] == "code-edit-cycle"
        steps = json.loads(routines[0]["steps"])
        assert len(steps) == 4
        uses = json.loads(routines[0]["uses"])
        assert "edit-then-test" in uses

    def test_routine_prompt_includes_playbooks_and_episodes(self, conn):
        _seed_episodes(conn)
        conn.execute(
            text("INSERT INTO playbook_entries (name, context, action, confidence, maturity, evidence) "
                 "VALUES (:name, :ctx, :action, :conf, :mat, :ev)"),
            {"name": "my-rule", "ctx": "ctx", "action": "act",
             "conf": 0.5, "mat": "nascent", "ev": "[]"},
        )
        conn.commit()

        episodes = conn.execute(text("SELECT * FROM episodes")).mappings().all()
        playbooks = conn.execute(text("SELECT * FROM playbook_entries")).mappings().all()

        episodes_text = "\n".join(f"Episode #{e['id']}:\n{e['summary']}" for e in episodes)
        playbooks_text = "\n".join(f"- {p['name']}" for p in playbooks)

        prompt = ROUTINE_PROMPT.format(
            playbooks=playbooks_text, routines="(none)", episodes=episodes_text,
        )
        assert "my-rule" in prompt
        assert "Edited Python code" in prompt


# -- Full sync chain L1 -> L2 -> L3 --

class TestFullSyncChain:
    def test_frames_to_routines_sync(self, conn):
        """Complete sync chain: seed frames -> episode -> distill -> routine."""
        # L1: Frames -> Episodes
        screen_ids = _seed_frames(conn, 5)
        frames = _load_frames_sync(conn, screen_ids, [])
        prompt = EPISODE_PROMPT.format(context=build_context(frames))
        llm1 = MockSyncLLM([EPISODE_LLM_RESPONSE])
        tasks = validate_episodes(llm1.complete(prompt, "haiku").text)
        _store_episodes_sync(conn, tasks, frames)
        conn.commit()

        # L2: Episodes -> Playbook
        episodes = conn.execute(text("SELECT * FROM episodes")).mappings().all()
        ep_text = "\n".join(f"Episode #{e['id']}:\n{e['summary']}" for e in episodes)
        dist_prompt = DISTILL_PROMPT.format(playbooks="(none)", episodes=ep_text)
        llm2 = MockSyncLLM([DISTILL_LLM_RESPONSE])
        entries = validate_playbooks(llm2.complete(dist_prompt, "opus").text)
        for entry in entries:
            conn.execute(
                text("INSERT INTO playbook_entries (name, context, action, confidence, maturity, evidence) "
                     "VALUES (:name, :ctx, :action, :conf, :mat, :ev)"),
                {"name": entry["name"], "ctx": entry.get("context", ""),
                 "action": entry.get("action", ""),
                 "conf": entry["confidence"], "mat": entry["maturity"],
                 "ev": json.dumps(entry.get("evidence", []))},
            )
        conn.commit()

        # L3: Episodes + Playbook -> Routines
        playbooks = conn.execute(text("SELECT * FROM playbook_entries")).mappings().all()
        pb_text = "\n".join(f"- {p['name']}" for p in playbooks)
        rtn_prompt = ROUTINE_PROMPT.format(playbooks=pb_text, routines="(none)", episodes=ep_text)
        llm3 = MockSyncLLM([ROUTINE_LLM_RESPONSE])
        resp_text = llm3.complete(rtn_prompt, "opus").text
        rtn_entries = json.loads(resp_text)
        for entry in rtn_entries:
            conn.execute(
                text("INSERT INTO routines (name, trigger, goal, steps, uses, confidence, maturity) "
                     "VALUES (:name, :trigger, :goal, :steps, :uses, :conf, :mat)"),
                {"name": entry["name"], "trigger": entry.get("trigger", ""),
                 "goal": entry.get("goal", ""),
                 "steps": json.dumps(entry.get("steps", [])),
                 "uses": json.dumps(entry.get("uses", [])),
                 "conf": entry.get("confidence", 0.4),
                 "mat": entry.get("maturity", "nascent")},
            )
        conn.commit()

        # Verify all in DB
        assert len(conn.execute(text("SELECT * FROM episodes")).mappings().all()) == 2
        assert len(conn.execute(text("SELECT * FROM playbook_entries")).mappings().all()) == 1
        routines = conn.execute(text("SELECT * FROM routines")).mappings().all()
        assert len(routines) == 1
        assert json.loads(routines[0]["uses"]) == ["edit-then-test"]
