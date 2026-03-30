"""Pipeline tests: LLM response parsing → validation → DB storage.

Tests the infrastructure layer: prompt construction, JSON parsing,
validation, and DB writes. Uses mock LLM (CannedLLM) to return fixed
JSON responses, verifying the full chain from LLM output to database.

The application layer (process_window, distill_playbooks, compose_routines)
delegates to Agent SDK + MCP tools — those paths are tested by Playwright E2E
with real LLM calls.
"""

import json

import pytest

from engine.infrastructure.llm.client import LLMClient
from engine.infrastructure.llm.types import LLMResponse
from engine.domain.observation.entity import Frame
from engine.infrastructure.pipeline.stages.extract import (
    build_context, extract_episodes, parse_llm_json,
)
from engine.infrastructure.pipeline.stages.validate import validate_playbooks


# ── Mock LLM that returns canned responses ──


class CannedLLM(LLMClient):
    """LLM client that returns pre-configured responses in order."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._call_index = 0
        self.calls: list[str] = []  # record prompts for inspection

    def complete(self, prompt: str, model: str) -> LLMResponse:
        self.calls.append(prompt)
        text = self._responses[self._call_index % len(self._responses)]
        self._call_index += 1
        return LLMResponse(text=text, input_tokens=100, output_tokens=50)

    async def acomplete(self, prompt: str, model: str) -> LLMResponse:
        return self.complete(prompt, model)


# ── Fixtures ──


@pytest.fixture(autouse=True)
def _memory_dir(tmp_path):
    import engine.infrastructure.persistence.memory_file as mf
    old = mf.MEMORY_DIR
    mf.MEMORY_DIR = tmp_path / "memory"
    yield
    mf.MEMORY_DIR = old


## db fixture is inherited from conftest.py


def make_frames(n: int = 5, source: str = "capture") -> list[Frame]:
    """Create N test frames with realistic data."""
    return [
        Frame(
            id=i + 1,
            source=source,
            timestamp=f"2026-03-16T10:{i:02d}:00Z",
            app_name="VSCode",
            window_name="editor.py",
            text=f"def function_{i}(): pass  # editing code",
        )
        for i in range(n)
    ]


EPISODE_LLM_RESPONSE = json.dumps([
    {
        "summary": "Edited Python code in VSCode, implementing functions",
        "method": "sequential editing with incremental saves",
        "turning_points": ["switched from function_2 to function_3 approach"],
        "avoidance": ["did not use debugger"],
        "under_pressure": False,
        "apps": ["VSCode"],
        "started_at": "2026-03-16T10:00:00Z",
        "ended_at": "2026-03-16T10:04:00Z",
    },
    {
        "summary": "Ran tests after editing",
        "method": "test-after-edit workflow",
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
        "when": "After making code changes",
        "then": "Execute test suite after each editing session",
        "because": "Catch regressions early",
        "boundary": None,
        "confidence": 0.7,
        "maturity": "developing",
        "evidence": [1, 2],
    },
])

ROUTINE_LLM_RESPONSE = json.dumps([
    {
        "name": "code-edit-cycle",
        "trigger": "Starting a new coding task",
        "goal": "Implement and verify code changes",
        "steps": [
            "Open relevant file in editor",
            "Make incremental changes",
            "IF tests exist THEN run tests ELSE manual check",
            "Commit when tests pass",
        ],
        "uses": ["edit-then-test"],
        "confidence": 0.6,
        "maturity": "nascent",
    },
])


# ── Helper: store episodes in DB ──


async def _store_episodes(db, tasks: list[dict], frames: list[Frame]) -> list[int]:
    """Store parsed episode dicts into DB, returning IDs."""
    frame_id_min = min(f.id for f in frames)
    frame_id_max = max(f.id for f in frames)
    frame_source = ",".join(sorted({f.source for f in frames}))

    episode_ids = []
    for task in tasks:
        summary = json.dumps({
            "summary": task.get("summary", ""),
            "method": task.get("method", ""),
            "turning_points": task.get("turning_points", []),
            "avoidance": task.get("avoidance", []),
            "under_pressure": task.get("under_pressure", False),
        }, ensure_ascii=False)
        episode_id = await db.insert_episode(
            summary=summary,
            app_names=json.dumps(task.get("apps", [])),
            frame_count=len(frames),
            started_at=task.get("started_at", frames[0].timestamp),
            ended_at=task.get("ended_at", frames[-1].timestamp),
            frame_id_min=frame_id_min,
            frame_id_max=frame_id_max,
            frame_source=frame_source,
        )
        episode_ids.append(episode_id)
    return episode_ids


# ── Episode extraction: build_context → LLM → parse → validate ──


class TestEpisodeExtraction:
    @pytest.mark.asyncio
    async def test_extract_episodes_full_chain(self, db):
        """build_context → CannedLLM → parse → validate → store in DB."""
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        frames = make_frames(5)

        tasks, resp = await extract_episodes(llm, build_context(frames))
        assert len(tasks) == 2

        episode_ids = await _store_episodes(db, tasks, frames)
        assert len(episode_ids) == 2

        episodes = await db.get_all_episodes()
        assert len(episodes) == 2
        summaries = [json.loads(ep["summary"])["summary"] for ep in episodes]
        assert any("VSCode" in s for s in summaries)

    def test_empty_frames_no_context(self):
        """No frames → empty context string."""
        assert build_context([]) == ""

    @pytest.mark.asyncio
    async def test_context_contains_frame_data(self):
        """Prompt sent to LLM should contain frame text."""
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        frames = make_frames(3)
        tasks, resp = await extract_episodes(llm, build_context(frames))

        prompt = llm.calls[0]
        assert "function_0" in prompt
        assert "VSCode" in prompt
        assert "editor.py" in prompt

    @pytest.mark.asyncio
    async def test_mixed_sources(self):
        """Frames from multiple sources should all appear in context."""
        frames = make_frames(3, source="capture") + [
            Frame(id=10, source="os_event", timestamp="2026-03-16T10:03:00Z",
                  app_name="shell_command", window_name="zsh", text="git status"),
        ]
        context = build_context(frames)
        assert "git status" in context
        assert "VSCode" in context

    @pytest.mark.asyncio
    async def test_usage_recorded(self, db):
        """LLM response metadata (tokens) should be available."""
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        tasks, resp = await extract_episodes(llm, build_context(make_frames(3)))
        assert resp.input_tokens > 0
        assert resp.output_tokens > 0

    @pytest.mark.asyncio
    async def test_store_episode_fields(self, db):
        """Verify stored episode has correct frame range and source."""
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        frames = make_frames(5)
        tasks, _ = await extract_episodes(llm, build_context(frames))
        await _store_episodes(db, tasks, frames)

        episodes = await db.get_all_episodes()
        vscode_ep = [ep for ep in episodes if "VSCode" in json.loads(ep["summary"])["summary"]][0]
        assert vscode_ep["app_names"] == '["VSCode"]'
        assert vscode_ep["frame_count"] == 5
        assert vscode_ep["frame_id_min"] == 1
        assert vscode_ep["frame_id_max"] == 5


# ── Playbook distillation: validate → store ──


class TestDistillParsing:
    def test_validate_playbook_response(self):
        """DISTILL_LLM_RESPONSE should pass validation."""
        entries = validate_playbooks(DISTILL_LLM_RESPONSE)
        assert len(entries) == 1
        assert entries[0]["name"] == "edit-then-test"
        assert entries[0]["confidence"] == 0.7
        assert entries[0]["maturity"] == "developing"

    @pytest.mark.asyncio
    async def test_store_playbook_entries(self, db):
        """Validated entries should be stored correctly in DB."""
        entries = validate_playbooks(DISTILL_LLM_RESPONSE)
        for entry in entries:
            action = json.dumps({
                "when": entry.get("when", ""),
                "then": entry.get("then", ""),
                "because": entry.get("because", ""),
                "boundary": entry.get("boundary"),
            }, ensure_ascii=False)
            await db.upsert_playbook(
                name=entry["name"],
                context=entry.get("when", ""),
                action=action,
                confidence=entry["confidence"],
                maturity=entry["maturity"],
                evidence=json.dumps(entry.get("evidence", [])),
            )

        playbooks = await db.get_all_playbooks()
        assert len(playbooks) == 1
        assert playbooks[0]["name"] == "edit-then-test"
        assert playbooks[0]["confidence"] == 0.7
        assert playbooks[0]["maturity"] == "developing"
        assert playbooks[0]["context"] == "After making code changes"
        action = json.loads(playbooks[0]["action"])
        assert action["when"] == "After making code changes"
        assert action["then"] == "Execute test suite after each editing session"
        assert action["because"] == "Catch regressions early"

    @pytest.mark.asyncio
    async def test_distill_with_llm_call(self, db):
        """CannedLLM → parse → validate → store: full parsing chain."""
        # Seed episodes first
        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        tasks, _ = await extract_episodes(llm_ep, build_context(make_frames(5)))
        await _store_episodes(db, tasks, make_frames(5))

        # Call LLM for distillation
        llm_dist = CannedLLM([DISTILL_LLM_RESPONSE])
        episodes = await db.get_all_episodes()
        episodes_text = "\n\n".join(f"Episode #{e['id']}:\n{e['summary']}" for e in episodes)
        resp = await llm_dist.acomplete(f"Distill from:\n{episodes_text}", "opus")

        entries = validate_playbooks(resp.text)
        assert len(entries) == 1

        # Verify prompt included episode data
        assert "Edited Python code" in llm_dist.calls[0]

    @pytest.mark.asyncio
    async def test_distill_writes_memory_file(self, db, tmp_path):
        """Playbook markdown files should be writable."""
        import engine.infrastructure.persistence.memory_file as mf
        mf.MEMORY_DIR = tmp_path / "memory"

        entries = validate_playbooks(DISTILL_LLM_RESPONSE)
        for entry in entries:
            mf.write_playbook(entry)

        md = tmp_path / "memory" / "playbooks" / "edit-then-test.md"
        assert md.exists()
        assert "edit-then-test" in md.read_text()


# ── Routine composition: parse → store ──


class TestRoutineParsing:
    def test_parse_routine_response(self):
        """ROUTINE_LLM_RESPONSE should parse correctly."""
        routines = parse_llm_json(ROUTINE_LLM_RESPONSE)
        assert len(routines) == 1
        assert routines[0]["name"] == "code-edit-cycle"
        assert len(routines[0]["steps"]) == 4
        assert "edit-then-test" in routines[0]["uses"]

    @pytest.mark.asyncio
    async def test_store_routines(self, db):
        """Parsed routines should be stored correctly in DB."""
        routines = parse_llm_json(ROUTINE_LLM_RESPONSE)
        for r in routines:
            await db.upsert_routine(
                name=r["name"],
                trigger=r.get("trigger", ""),
                goal=r.get("goal", ""),
                steps=json.dumps(r.get("steps", []), ensure_ascii=False),
                uses=json.dumps(r.get("uses", []), ensure_ascii=False),
                confidence=r.get("confidence", 0.4),
                maturity=r.get("maturity", "nascent"),
            )

        stored = await db.get_all_routines()
        assert len(stored) == 1
        assert stored[0]["name"] == "code-edit-cycle"
        steps = json.loads(stored[0]["steps"])
        assert len(steps) == 4
        uses = json.loads(stored[0]["uses"])
        assert "edit-then-test" in uses

    @pytest.mark.asyncio
    async def test_routine_writes_memory_file(self, db, tmp_path):
        """Routine markdown files should be writable."""
        import engine.infrastructure.persistence.memory_file as mf
        mf.MEMORY_DIR = tmp_path / "memory"

        routines = parse_llm_json(ROUTINE_LLM_RESPONSE)
        for r in routines:
            mf.write_routine(r)

        md = tmp_path / "memory" / "routines" / "code-edit-cycle.md"
        assert md.exists()
        content = md.read_text()
        assert "code-edit-cycle" in content
        assert "edit-then-test" in content


# ── Full chain: episodes → playbook → routines all in DB ──


class TestFullChain:
    @pytest.mark.asyncio
    async def test_episodes_to_routines_complete(self, db):
        """Full chain: LLM episodes → validate → store → LLM distill → validate → store → LLM routines → store."""
        # L1: Episode extraction
        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        tasks, _ = await extract_episodes(llm_ep, build_context(make_frames(5)))
        episode_ids = await _store_episodes(db, tasks, make_frames(5))
        assert len(episode_ids) == 2

        # L2: Distillation
        entries = validate_playbooks(DISTILL_LLM_RESPONSE)
        for entry in entries:
            action = json.dumps({
                "when": entry.get("when", ""),
                "then": entry.get("then", ""),
                "because": entry.get("because", ""),
                "boundary": entry.get("boundary"),
            }, ensure_ascii=False)
            await db.upsert_playbook(
                name=entry["name"], context=entry.get("when", ""),
                action=action, confidence=entry["confidence"],
                maturity=entry["maturity"],
                evidence=json.dumps(entry.get("evidence", [])),
            )

        # L3: Routine composition
        routines = parse_llm_json(ROUTINE_LLM_RESPONSE)
        for r in routines:
            await db.upsert_routine(
                name=r["name"], trigger=r.get("trigger", ""),
                goal=r.get("goal", ""),
                steps=json.dumps(r.get("steps", []), ensure_ascii=False),
                uses=json.dumps(r.get("uses", []), ensure_ascii=False),
                confidence=r.get("confidence", 0.4),
                maturity=r.get("maturity", "nascent"),
            )

        # Verify everything in DB
        episodes = await db.get_all_episodes()
        playbooks = await db.get_all_playbooks()
        stored_routines = await db.get_all_routines()
        assert len(episodes) == 2
        assert len(playbooks) == 1
        assert len(stored_routines) == 1

        # Routine references playbook entry
        uses = json.loads(stored_routines[0]["uses"])
        assert playbooks[0]["name"] in uses
