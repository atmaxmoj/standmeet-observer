"""End-to-end pipeline tests: frames → episodes → playbook → routines.

Mock LLM returns fixed JSON. Tests verify the full chain from input to DB storage.
These tests lock down current behavior before refactoring.
"""

import json

import pytest

from engine.llm import LLMClient, LLMResponse
from engine.etl.entities import Frame
from engine.pipeline.episode import process_window
from engine.pipeline.distill import daily_distill
from engine.pipeline.routines import daily_routines


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
    import engine.storage.memory_file as mf
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
        "context": "After making code changes",
        "intuition": "Run tests to verify",
        "action": "Execute test suite after each editing session",
        "why": "Catch regressions early",
        "counterexample": None,
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


# ── E2E: Episode extraction ──


class TestEpisodeE2E:
    @pytest.mark.asyncio
    async def test_frames_to_episodes_full_chain(self, db):
        """frames → build_context → LLM → parse → store in DB."""
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        frames = make_frames(5)

        episode_ids = await process_window(llm, db, frames)

        # Episodes stored in DB
        assert len(episode_ids) == 2
        episodes = await db.get_all_episodes()
        assert len(episodes) == 2

        # Check episode data (order may vary in PostgreSQL)
        summaries = [json.loads(ep["summary"])["summary"] for ep in episodes]
        assert any("VSCode" in s for s in summaries)
        # Find the VSCode episode
        vscode_ep = [ep for ep in episodes if "VSCode" in json.loads(ep["summary"])["summary"]][0]
        assert vscode_ep["app_names"] == '["VSCode"]'
        assert vscode_ep["frame_count"] == 5
        assert vscode_ep["frame_id_min"] == 1
        assert vscode_ep["frame_id_max"] == 5

    @pytest.mark.asyncio
    async def test_empty_frames_returns_empty(self, db):
        """No frames → no episodes, no LLM call."""
        llm = CannedLLM(["should not be called"])
        episode_ids = await process_window(llm, db, [])
        assert episode_ids == []
        assert llm._call_index == 0

    @pytest.mark.asyncio
    async def test_usage_recorded(self, db):
        """LLM usage (tokens, cost) should be recorded."""
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm, db, make_frames(3))

        usage = await db.get_usage_summary(days=1)
        assert usage["total_input_tokens"] > 0

    @pytest.mark.asyncio
    async def test_pipeline_log_recorded(self, db):
        """Prompt and response should be logged."""
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm, db, make_frames(3))

        logs, total = await db.get_pipeline_logs(limit=10)
        episode_logs = [log for log in logs if log["stage"] == "episode"]
        assert len(episode_logs) == 1
        assert len(episode_logs[0]["prompt"]) > 0
        assert len(episode_logs[0]["response"]) > 0

    @pytest.mark.asyncio
    async def test_context_contains_frame_data(self, db):
        """The prompt sent to LLM should contain frame text."""
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        frames = make_frames(3)
        await process_window(llm, db, frames)

        prompt = llm.calls[0]
        assert "function_0" in prompt
        assert "VSCode" in prompt
        assert "editor.py" in prompt

    @pytest.mark.asyncio
    async def test_mixed_sources(self, db):
        """Frames from multiple sources should all appear in context."""
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        frames = make_frames(3, source="capture") + [
            Frame(id=10, source="os_event", timestamp="2026-03-16T10:03:00Z",
                  app_name="shell_command", window_name="zsh", text="git status"),
        ]
        await process_window(llm, db, frames)

        prompt = llm.calls[0]
        assert "git status" in prompt
        episodes = await db.get_all_episodes()
        assert episodes[0]["frame_source"] in ("capture,os_event", "os_event,capture")


# ── E2E: Distillation ──


class TestDistillE2E:
    @pytest.mark.asyncio
    async def test_episodes_to_playbook_full_chain(self, db):
        """episodes in DB → LLM → parse → playbook entries in DB."""
        # Seed episodes
        llm = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm, db, make_frames(5))

        # Run distill
        llm_distill = CannedLLM([DISTILL_LLM_RESPONSE])
        count = await daily_distill(llm_distill, db)

        assert count == 1
        playbooks = await db.get_all_playbooks()
        assert len(playbooks) == 1
        assert playbooks[0]["name"] == "edit-then-test"
        assert playbooks[0]["confidence"] == 0.7
        assert playbooks[0]["maturity"] == "developing"

    @pytest.mark.asyncio
    async def test_distill_no_episodes_skips(self, db):
        """No episodes → skip distillation, no LLM call."""
        llm = CannedLLM(["should not be called"])
        count = await daily_distill(llm, db)
        assert count == 0
        assert llm._call_index == 0

    @pytest.mark.asyncio
    async def test_distill_prompt_contains_episodes(self, db):
        """Distill prompt should include episode summaries."""
        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm_ep, db, make_frames(5))

        llm_dist = CannedLLM([DISTILL_LLM_RESPONSE])
        await daily_distill(llm_dist, db)

        prompt = llm_dist.calls[0]
        assert "Edited Python code" in prompt

    @pytest.mark.asyncio
    async def test_distill_includes_existing_playbooks(self, db):
        """Distill prompt should include existing playbook entries."""
        # Seed episode + first distill
        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm_ep, db, make_frames(5))
        llm_d1 = CannedLLM([DISTILL_LLM_RESPONSE])
        await daily_distill(llm_d1, db)

        # Second distill should see existing entries
        llm_d2 = CannedLLM([DISTILL_LLM_RESPONSE])
        await daily_distill(llm_d2, db)

        prompt = llm_d2.calls[0]
        assert "edit-then-test" in prompt

    @pytest.mark.asyncio
    async def test_distill_writes_memory_file(self, db, tmp_path):
        """Distill should write playbook markdown files."""
        import engine.storage.memory_file as mf
        mf.MEMORY_DIR = tmp_path / "memory"

        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm_ep, db, make_frames(5))
        llm_dist = CannedLLM([DISTILL_LLM_RESPONSE])
        await daily_distill(llm_dist, db)

        md = tmp_path / "memory" / "playbooks" / "edit-then-test.md"
        assert md.exists()
        assert "edit-then-test" in md.read_text()

    @pytest.mark.asyncio
    async def test_distill_records_usage_and_log(self, db):
        """Distill should record usage and pipeline log."""
        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm_ep, db, make_frames(5))
        llm_dist = CannedLLM([DISTILL_LLM_RESPONSE])
        await daily_distill(llm_dist, db)

        logs, _ = await db.get_pipeline_logs(limit=10)
        distill_logs = [log for log in logs if log["stage"] == "distill"]
        assert len(distill_logs) == 1


# ── E2E: Routines ──


class TestRoutineE2E:
    @pytest.mark.asyncio
    async def test_full_chain_episodes_to_routines(self, db):
        """episodes + playbook → LLM → routines in DB."""
        # Seed episodes + playbook
        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm_ep, db, make_frames(5))
        llm_dist = CannedLLM([DISTILL_LLM_RESPONSE])
        await daily_distill(llm_dist, db)

        # Run routine extraction
        llm_rtn = CannedLLM([ROUTINE_LLM_RESPONSE])
        count = await daily_routines(llm_rtn, db)

        assert count == 1
        routines = await db.get_all_routines()
        assert len(routines) == 1
        assert routines[0]["name"] == "code-edit-cycle"
        steps = json.loads(routines[0]["steps"])
        assert len(steps) == 4
        uses = json.loads(routines[0]["uses"])
        assert "edit-then-test" in uses

    @pytest.mark.asyncio
    async def test_routine_no_episodes_skips(self, db):
        """No episodes → skip, no LLM call."""
        llm = CannedLLM(["should not be called"])
        count = await daily_routines(llm, db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_routine_prompt_contains_playbook_and_episodes(self, db):
        """Routine prompt should include both playbook entries and episodes."""
        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm_ep, db, make_frames(5))
        llm_dist = CannedLLM([DISTILL_LLM_RESPONSE])
        await daily_distill(llm_dist, db)

        llm_rtn = CannedLLM([ROUTINE_LLM_RESPONSE])
        await daily_routines(llm_rtn, db)

        prompt = llm_rtn.calls[0]
        assert "edit-then-test" in prompt  # playbook entry
        assert "Edited Python code" in prompt  # episode

    @pytest.mark.asyncio
    async def test_routine_writes_memory_file(self, db, tmp_path):
        """Routine extraction should write markdown files."""
        import engine.storage.memory_file as mf
        mf.MEMORY_DIR = tmp_path / "memory"

        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        await process_window(llm_ep, db, make_frames(5))
        llm_dist = CannedLLM([DISTILL_LLM_RESPONSE])
        await daily_distill(llm_dist, db)
        llm_rtn = CannedLLM([ROUTINE_LLM_RESPONSE])
        await daily_routines(llm_rtn, db)

        md = tmp_path / "memory" / "routines" / "code-edit-cycle.md"
        assert md.exists()
        content = md.read_text()
        assert "code-edit-cycle" in content
        assert "edit-then-test" in content


# ── E2E: Full pipeline chain ──


class TestFullChainE2E:
    @pytest.mark.asyncio
    async def test_frames_to_routines_complete(self, db):
        """Full chain: frames → episodes → playbook → routines, all in DB."""
        # L1: Episode extraction
        llm_ep = CannedLLM([EPISODE_LLM_RESPONSE])
        episode_ids = await process_window(llm_ep, db, make_frames(5))
        assert len(episode_ids) == 2

        # L2: Distillation
        llm_dist = CannedLLM([DISTILL_LLM_RESPONSE])
        pb_count = await daily_distill(llm_dist, db)
        assert pb_count == 1

        # L3: Routine extraction
        llm_rtn = CannedLLM([ROUTINE_LLM_RESPONSE])
        rtn_count = await daily_routines(llm_rtn, db)
        assert rtn_count == 1

        # Verify everything in DB
        episodes = await db.get_all_episodes()
        playbooks = await db.get_all_playbooks()
        routines = await db.get_all_routines()
        assert len(episodes) == 2
        assert len(playbooks) == 1
        assert len(routines) == 1

        # Routine references playbook entry
        uses = json.loads(routines[0]["uses"])
        assert playbooks[0]["name"] in uses
