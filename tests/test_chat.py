"""Tests for memory chat tool dispatch and proposal logic."""

import pytest
import aiosqlite

from engine.db import DB
from engine.api.chat import _read_tool, _handle_tool, _make_read_tools


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
