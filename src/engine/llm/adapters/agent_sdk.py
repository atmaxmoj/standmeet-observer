"""AgentSDK LLM client — for OAuth token users.

Uses Claude Agent SDK's query() for LLM calls (single-turn, no MCP).
Required because Anthropic's direct API doesn't support OAuth tokens.
"""

import asyncio
import logging
import os

from engine.llm.client import LLMClient
from engine.llm.types import ContentBlock, LLMResponse, MessageResponse

logger = logging.getLogger(__name__)


class AgentSDKClient(LLMClient):
    """Uses Claude Agent SDK query() for LLM calls. OAuth token only."""

    def __init__(self, auth_token: str = ""):
        self._auth_token = auth_token

    def _build_env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        if self._auth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self._auth_token
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
            env.pop("ANTHROPIC_API_KEY", None)
        return env

    def complete(self, prompt: str, model: str) -> LLMResponse:
        return asyncio.run(self.acomplete(prompt, model))

    async def acomplete(self, prompt: str, model: str) -> LLMResponse:
        from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

        result_text = ""
        cost_usd = None
        usage: dict = {}
        async for msg in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                model=model,
                max_turns=1,
                permission_mode="bypassPermissions",
                tools=[],
                env=self._build_env(),
            ),
        ):
            if isinstance(msg, ResultMessage):
                result_text = msg.result or ""
                cost_usd = msg.total_cost_usd
                usage = msg.usage or {}

        return LLMResponse(
            text=result_text,
            cost_usd=cost_usd,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    async def amessages_create(
        self,
        *,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        system: str = "",
        max_tokens: int = 4096,
    ) -> MessageResponse:
        """Single-turn LLM call via Agent SDK. Supports tools via text parsing."""
        # Build a single prompt from messages
        parts = []
        if system:
            parts.append(f"[System] {system}")
        for m in messages:
            role = m["role"]
            content = m["content"] if isinstance(m["content"], str) else str(m["content"])
            parts.append(f"[{role}] {content}")
        if tools:
            parts.append(f"[Available tools] {[t['name'] for t in tools]}")
        prompt = "\n\n".join(parts)

        resp = await self.acomplete(prompt, model)
        return MessageResponse(
            content=[ContentBlock(type="text", text=resp.text)],
            stop_reason="end_turn",
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )
