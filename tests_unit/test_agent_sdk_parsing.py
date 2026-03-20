"""Unit tests for AgentSDKClient XML tool_use parsing (no DB needed)."""

import pytest
from unittest.mock import AsyncMock, patch

from engine.llm.adapters.agent_sdk import AgentSDKClient
from engine.llm.types import LLMResponse


class TestAgentSDKToolParsing:
    """Test that AgentSDKClient.amessages_create parses XML tool_use tags."""

    @pytest.mark.asyncio
    async def test_parses_single_tool_use(self):
        """XML tool_use tag is parsed into ContentBlock(type='tool_use')."""
        client = AgentSDKClient(auth_token="test")
        mock_resp = LLMResponse(
            text='Let me check.\n<tool_use><name>get_recent_episodes</name><input>{"limit": 5}</input></tool_use>',
            input_tokens=100, output_tokens=50,
        )
        with patch.object(client, "acomplete", new_callable=AsyncMock, return_value=mock_resp):
            resp = await client.amessages_create(
                messages=[{"role": "user", "content": "Show episodes"}],
                model="haiku",
                tools=[{"name": "get_recent_episodes", "description": "Get episodes", "input_schema": {"type": "object"}}],
            )
        assert resp.stop_reason == "tool_use"
        tool_blocks = [b for b in resp.content if b.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].tool_name == "get_recent_episodes"
        assert tool_blocks[0].tool_input == {"limit": 5}
        assert tool_blocks[0].tool_use_id.startswith("toolu_")
        text_blocks = [b for b in resp.content if b.type == "text"]
        assert len(text_blocks) == 1
        assert "Let me check" in text_blocks[0].text

    @pytest.mark.asyncio
    async def test_parses_multiple_tool_uses(self):
        """Multiple XML tool_use tags are all parsed."""
        client = AgentSDKClient(auth_token="test")
        mock_resp = LLMResponse(
            text=(
                '<tool_use><name>get_recent_episodes</name><input>{"limit": 3}</input></tool_use>'
                '<tool_use><name>get_playbooks</name><input>{}</input></tool_use>'
            ),
            input_tokens=100, output_tokens=50,
        )
        with patch.object(client, "acomplete", new_callable=AsyncMock, return_value=mock_resp):
            resp = await client.amessages_create(
                messages=[{"role": "user", "content": "Overview"}],
                model="haiku",
                tools=[
                    {"name": "get_recent_episodes", "description": "Get episodes", "input_schema": {}},
                    {"name": "get_playbooks", "description": "Get playbooks", "input_schema": {}},
                ],
            )
        tool_blocks = [b for b in resp.content if b.type == "tool_use"]
        assert len(tool_blocks) == 2
        assert tool_blocks[0].tool_name == "get_recent_episodes"
        assert tool_blocks[1].tool_name == "get_playbooks"

    @pytest.mark.asyncio
    async def test_no_tool_use_returns_text(self):
        """Response without tool_use tags returns plain text."""
        client = AgentSDKClient(auth_token="test")
        mock_resp = LLMResponse(text="Here is my answer.", input_tokens=50, output_tokens=20)
        with patch.object(client, "acomplete", new_callable=AsyncMock, return_value=mock_resp):
            resp = await client.amessages_create(
                messages=[{"role": "user", "content": "Hi"}],
                model="haiku",
            )
        assert resp.stop_reason == "end_turn"
        assert len(resp.content) == 1
        assert resp.content[0].type == "text"
        assert resp.content[0].text == "Here is my answer."
