"""Tests for memory chat tool dispatch, proposal logic, and endpoint integration."""

import json

import pytest
import aiosqlite
from httpx import ASGITransport, AsyncClient

from engine.db import DB
from engine.api.chat import _read_tool, _handle_tool, _make_read_tools
from engine.llm import ContentBlock, MessageResponse, LLMClient, LLMResponse


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "test.db")
    d = DB(path)
    await d.connect()
    yield d
    await d.close()


@pytest.fixture
async def seeded_db(db):
    """DB with some test data."""
    await db.insert_frame(
        timestamp="2026-03-16T10:00:00",
        app_name="VSCode",
        window_name="editor.py",
        text="def hello(): pass",
        display_id=1,
        image_hash="abc123",
    )
    await db.insert_audio_frame(
        timestamp="2026-03-16T10:05:00",
        text="testing audio",
        language="en",
        duration_seconds=5.0,
        source="mic",
    )
    await db.insert_os_event(
        timestamp="2026-03-16T10:10:00",
        event_type="shell_command",
        source="zsh",
        data="git status",
    )
    # Insert an episode
    await db._conn.execute(
        "INSERT INTO episodes (summary, app_names, frame_count, started_at, ended_at, frame_id_min, frame_id_max, frame_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('{"summary": "Coding in VSCode"}', "VSCode", 5, "2026-03-16T10:00:00", "2026-03-16T10:30:00", 1, 5, "screen"),
    )
    await db._conn.commit()
    # Insert a playbook entry
    await db.upsert_playbook(
        name="use-git-frequently",
        context="Developer workflow",
        action="Commits frequently during coding sessions",
        confidence=0.8,
        evidence="[1]",
        maturity="developing",
    )
    return db


class TestReadTools:
    @pytest.mark.asyncio
    async def test_search_episodes(self, seeded_db):
        result = await _read_tool(seeded_db, "search_episodes", {"query": "VSCode"})
        assert isinstance(result, list)
        assert len(result) == 1
        assert "VSCode" in result[0]["summary"]

    @pytest.mark.asyncio
    async def test_search_episodes_no_match(self, seeded_db):
        result = await _read_tool(seeded_db, "search_episodes", {"query": "nonexistent"})
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_episodes(self, seeded_db):
        result = await _read_tool(seeded_db, "get_recent_episodes", {"days": 7})
        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_get_playbooks(self, seeded_db):
        result = await _read_tool(seeded_db, "get_playbooks", {})
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "use-git-frequently"

    @pytest.mark.asyncio
    async def test_get_playbooks_with_search(self, seeded_db):
        result = await _read_tool(seeded_db, "get_playbooks", {"search": "git"})
        assert len(result) == 1
        result = await _read_tool(seeded_db, "get_playbooks", {"search": "nonexistent"})
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_playbook_history(self, seeded_db):
        result = await _read_tool(seeded_db, "get_playbook_history", {"name": "use-git-frequently"})
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_frames(self, seeded_db):
        result = await _read_tool(seeded_db, "get_frames", {"limit": 10})
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["app_name"] == "VSCode"

    @pytest.mark.asyncio
    async def test_get_frames_with_search(self, seeded_db):
        result = await _read_tool(seeded_db, "get_frames", {"search": "hello"})
        assert len(result) == 1
        result = await _read_tool(seeded_db, "get_frames", {"search": "nonexistent"})
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_audio(self, seeded_db):
        result = await _read_tool(seeded_db, "get_audio", {"limit": 10})
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_os_events(self, seeded_db):
        result = await _read_tool(seeded_db, "get_os_events", {"limit": 10})
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["data"] == "git status"

    @pytest.mark.asyncio
    async def test_get_os_events_filtered(self, seeded_db):
        result = await _read_tool(seeded_db, "get_os_events", {"event_type": "shell_command"})
        assert len(result) == 1
        result = await _read_tool(seeded_db, "get_os_events", {"event_type": "browser_url"})
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_usage(self, seeded_db):
        result = await _read_tool(seeded_db, "get_usage", {"days": 7})
        assert isinstance(result, dict)
        assert "total_cost_usd" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_none(self, seeded_db):
        result = await _read_tool(seeded_db, "nonexistent_tool", {})
        assert result is None


class TestHandleTool:
    @pytest.mark.asyncio
    async def test_read_tool_returns_no_proposal(self, seeded_db):
        result, proposal = await _handle_tool(seeded_db, "get_playbooks", {})
        assert isinstance(result, list)
        assert proposal is None

    @pytest.mark.asyncio
    async def test_propose_delete(self, seeded_db):
        result, proposal = await _handle_tool(seeded_db, "propose_delete", {
            "table": "episodes", "ids": [1, 2], "reason": "outdated data",
        })
        assert result["status"] == "proposal_created"
        assert proposal is not None
        assert proposal["type"] == "delete"
        assert proposal["table"] == "episodes"
        assert proposal["ids"] == [1, 2]
        assert proposal["reason"] == "outdated data"

    @pytest.mark.asyncio
    async def test_propose_delete_does_not_execute(self, seeded_db):
        """Proposals must NOT actually delete anything."""
        _, _ = await _handle_tool(seeded_db, "propose_delete", {
            "table": "episodes", "ids": [1], "reason": "test",
        })
        # Episode should still exist
        episodes = await seeded_db.get_all_episodes()
        assert len(episodes) == 1

    @pytest.mark.asyncio
    async def test_propose_update_playbook(self, seeded_db):
        result, proposal = await _handle_tool(seeded_db, "propose_update_playbook", {
            "name": "use-git-frequently",
            "confidence": 0.9,
            "reason": "more evidence observed",
        })
        assert result["status"] == "proposal_created"
        assert proposal["type"] == "update_playbook"
        assert proposal["fields"]["name"] == "use-git-frequently"
        assert proposal["fields"]["confidence"] == 0.9
        assert proposal["reason"] == "more evidence observed"

    @pytest.mark.asyncio
    async def test_propose_update_does_not_execute(self, seeded_db):
        """Proposals must NOT actually modify anything."""
        _, _ = await _handle_tool(seeded_db, "propose_update_playbook", {
            "name": "use-git-frequently",
            "confidence": 0.1,
            "reason": "test",
        })
        playbooks = await seeded_db.get_all_playbooks()
        assert playbooks[0]["confidence"] == 0.8  # unchanged

    @pytest.mark.asyncio
    async def test_unknown_tool(self, seeded_db):
        result, proposal = await _handle_tool(seeded_db, "nonexistent", {})
        assert "error" in result
        assert proposal is None


class TestToolDefinitions:
    def test_all_read_tools_have_handlers(self, tmp_path):
        """Every tool defined in _make_read_tools should be handled by _read_tool or _handle_tool."""
        # We just check the tool names are recognized
        tools = _make_read_tools(None)
        tool_names = {t["name"] for t in tools}
        # Known tool names
        expected = {
            "search_episodes", "get_recent_episodes", "get_playbooks",
            "get_playbook_history", "get_frames", "get_audio", "get_os_events",
            "get_usage", "propose_delete", "propose_update_playbook",
        }
        assert tool_names == expected

    def test_tool_schemas_valid(self, tmp_path):
        """Tool schemas should have required fields."""
        tools = _make_read_tools(None)
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "input_schema" in t
            assert t["input_schema"]["type"] == "object"


# ── Endpoint integration tests (mock LLM, real DB) ──


class MockLLMClient(LLMClient):
    """LLM client that returns scripted responses for testing."""

    def __init__(self, responses: list[MessageResponse]):
        self._responses = list(responses)
        self._call_count = 0

    def complete(self, prompt: str, model: str) -> LLMResponse:
        return LLMResponse(text="mock")

    async def acomplete(self, prompt: str, model: str) -> LLMResponse:
        return LLMResponse(text="mock")

    async def amessages_create(self, *, messages, model, tools=None, system="", max_tokens=4096):
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp


def _make_app(db, llm):
    """Create a FastAPI app with mocked state."""
    from fastapi import FastAPI
    from engine.api.chat import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.db = db
    app.state.llm = llm
    return app


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    """Parse SSE text into list of (event, data) tuples."""
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = ""
        data_str = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if event_name and data_str:
            events.append((event_name, json.loads(data_str)))
    return events


class TestChatEndpoint:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, seeded_db):
        """LLM returns text directly → SSE text event with reply."""
        llm = MockLLMClient([
            MessageResponse(
                content=[ContentBlock(type="text", text="Here are your recent episodes.")],
                stop_reason="end_turn",
                input_tokens=100, output_tokens=50,
            ),
        ])
        app = _make_app(seeded_db, llm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/memory/chat", json={"messages": [
                {"role": "user", "content": "What did I do recently?"},
            ]})
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        assert len(events) == 1
        assert events[0][0] == "text"
        assert events[0][1]["content"] == "Here are your recent episodes."
        assert events[0][1]["input_tokens"] == 100

    @pytest.mark.asyncio
    async def test_tool_call_then_text(self, seeded_db):
        """LLM calls a tool, then returns text → SSE tool_call + text events."""
        llm = MockLLMClient([
            # Turn 1: tool call
            MessageResponse(
                content=[ContentBlock(
                    type="tool_use", tool_name="search_episodes",
                    tool_input={"query": "VSCode"}, tool_use_id="tool_1",
                )],
                stop_reason="tool_use",
                input_tokens=80, output_tokens=30,
            ),
            # Turn 2: text response
            MessageResponse(
                content=[ContentBlock(type="text", text="Found 1 episode about VSCode.")],
                stop_reason="end_turn",
                input_tokens=200, output_tokens=40,
            ),
        ])
        app = _make_app(seeded_db, llm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/memory/chat", json={"messages": [
                {"role": "user", "content": "Search for VSCode"},
            ]})
        events = _parse_sse(resp.text)
        assert len(events) == 2
        assert events[0][0] == "tool_call"
        assert events[0][1]["name"] == "search_episodes"
        assert events[0][1]["label"] == "Searching episodes"
        assert events[1][0] == "text"
        assert "VSCode" in events[1][1]["content"]
        # Token counts should be summed
        assert events[1][1]["input_tokens"] == 280

    @pytest.mark.asyncio
    async def test_proposal_returned_in_text_event(self, seeded_db):
        """Proposal tools should return proposals in the final text event."""
        llm = MockLLMClient([
            MessageResponse(
                content=[ContentBlock(
                    type="tool_use", tool_name="propose_delete",
                    tool_input={"table": "episodes", "ids": [1], "reason": "outdated"},
                    tool_use_id="tool_1",
                )],
                stop_reason="tool_use",
                input_tokens=80, output_tokens=30,
            ),
            MessageResponse(
                content=[ContentBlock(type="text", text="I've proposed deleting the episode.")],
                stop_reason="end_turn",
                input_tokens=150, output_tokens=20,
            ),
        ])
        app = _make_app(seeded_db, llm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/memory/chat", json={"messages": [
                {"role": "user", "content": "Delete episode 1"},
            ]})
        events = _parse_sse(resp.text)
        text_event = [e for e in events if e[0] == "text"][0][1]
        assert len(text_event["proposals"]) == 1
        assert text_event["proposals"][0]["type"] == "delete"
        assert text_event["proposals"][0]["ids"] == [1]

    @pytest.mark.asyncio
    async def test_unsupported_llm_returns_error(self, seeded_db):
        """LLM that doesn't support amessages_create → SSE error event."""
        llm = MockLLMClient([])  # won't be called
        # Override amessages_create to raise
        llm.amessages_create = lambda **kw: (_ for _ in ()).throw(NotImplementedError("nope"))
        app = _make_app(seeded_db, llm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/memory/chat", json={"messages": [
                {"role": "user", "content": "hello"},
            ]})
        events = _parse_sse(resp.text)
        assert len(events) == 1
        assert events[0][0] == "error"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self, seeded_db):
        """Multiple sequential tool calls before final text."""
        llm = MockLLMClient([
            MessageResponse(
                content=[ContentBlock(
                    type="tool_use", tool_name="get_playbooks",
                    tool_input={}, tool_use_id="t1",
                )],
                stop_reason="tool_use",
                input_tokens=50, output_tokens=20,
            ),
            MessageResponse(
                content=[ContentBlock(
                    type="tool_use", tool_name="get_recent_episodes",
                    tool_input={"days": 3}, tool_use_id="t2",
                )],
                stop_reason="tool_use",
                input_tokens=80, output_tokens=30,
            ),
            MessageResponse(
                content=[ContentBlock(type="text", text="Summary of your activity.")],
                stop_reason="end_turn",
                input_tokens=120, output_tokens=40,
            ),
        ])
        app = _make_app(seeded_db, llm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/memory/chat", json={"messages": [
                {"role": "user", "content": "Give me a summary"},
            ]})
        events = _parse_sse(resp.text)
        tool_events = [e for e in events if e[0] == "tool_call"]
        assert len(tool_events) == 2
        assert tool_events[0][1]["name"] == "get_playbooks"
        assert tool_events[1][1]["name"] == "get_recent_episodes"
        text_event = [e for e in events if e[0] == "text"][0][1]
        assert text_event["content"] == "Summary of your activity."
        assert text_event["input_tokens"] == 250  # 50+80+120
