"""AgentService — unified facade for all LLM + tool interactions.

Each application layer creates its own instance with settings.
AgentService internally decides whether to use Direct API or Agent SDK
based on available credentials.

Usage:
    from engine.config import Settings
    agent = AgentService(Settings())
    response = agent.complete(prompt, model)
    result = agent.run_with_mcp(prompt, mcp_server, ...)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from engine.infrastructure.agent import sdk
from engine.config import Settings
from engine.infrastructure.llm.types import LLMResponse, ToolDef

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from engine.infrastructure.llm.client import LLMClient

logger = logging.getLogger(__name__)

# Re-export for callers
AgentResult = sdk.AgentResult


class AgentService:
    """Facade for LLM completion + agentic tool calling.

    Internally routes to Direct API (if api_key) or Agent SDK (if auth_token).
    Callers never need to know which path is used.
    """

    def __init__(self, settings: Settings, *, llm_override: LLMClient | None = None):
        self._settings = settings
        self._api_key = settings.anthropic_api_key
        self._auth_token = settings.claude_code_oauth_token
        self._llm = llm_override  # set for testing, otherwise lazy init

    @property
    def uses_sdk(self) -> bool:
        """True if using Agent SDK (OAuth), False if Direct API."""
        if self._llm is not None:
            return False  # explicit LLM override = direct API path
        return bool(self._auth_token) and not bool(self._api_key)

    def _get_llm(self):
        """Lazy-init Direct API client."""
        if self._llm is None:
            from engine.infrastructure.llm.anthropic import DirectAPIClient
            if not self._api_key:
                raise ValueError("No API key for DirectAPIClient")
            self._llm = DirectAPIClient(api_key=self._api_key)
        return self._llm

    # ── Simple completion ──

    def complete(self, prompt: str, model: str) -> LLMResponse:
        """Single-turn text completion. Sync."""
        if self.uses_sdk:
            return sdk.complete(prompt, model, self._auth_token)
        return self._get_llm().complete(prompt, model)

    async def acomplete(self, prompt: str, model: str) -> LLMResponse:
        """Single-turn text completion. Async."""
        if self.uses_sdk:
            return await sdk.acomplete(prompt, model, self._auth_token)
        return await self._get_llm().acomplete(prompt, model)

    # ── MCP agentic run ──

    async def arun_with_mcp(
        self,
        prompt: str,
        mcp_server_config,
        mcp_name: str,
        stage: str,
        session: Session,
        model: str = "",
        max_turns: int = 40,
    ) -> sdk.AgentResult:
        """Multi-turn agentic run with MCP tools. Async.

        Prefer this from async callers to avoid nested event loops.
        """
        auth_token = self._auth_token or ""
        return await sdk.arun_with_mcp(
            prompt=prompt,
            mcp_server_config=mcp_server_config,
            mcp_name=mcp_name,
            stage=stage,
            session=session,
            auth_token=auth_token,
            model=model,
            max_turns=max_turns,
        )

    def run_with_mcp(
        self,
        prompt: str,
        mcp_server_config,
        mcp_name: str,
        stage: str,
        session: Session,
        model: str = "",
        max_turns: int = 40,
    ) -> sdk.AgentResult:
        """Multi-turn agentic run with MCP tools. Sync.

        Only use from sync context (Huey tasks). For async callers,
        use arun_with_mcp to avoid nested event loops.
        """
        auth_token = self._auth_token or ""
        return sdk.run_with_mcp(
            prompt=prompt,
            mcp_server_config=mcp_server_config,
            mcp_name=mcp_name,
            stage=stage,
            session=session,
            auth_token=auth_token,
            model=model,
            max_turns=max_turns,
        )

    # ── Native API streaming tool loop (for chat with DirectAPIClient) ──

    async def astream(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict],
        tool_handlers: dict,
        system: str = "",
        max_turns: int = 8,
    ):
        """Async generator — yields events during multi-turn tool loop.

        Only works with Direct API (native tool_use blocks).
        tool_handlers values can be sync or async callables.

        Yields dicts with "type" key:
          {"type": "tool_call", "name": ..., "input": ..., "result": ...}
          {"type": "response", "content": [...], "stop_reason": ..., ...}
          {"type": "error", "message": ...}
        """
        llm = self._get_llm()
        total_input = 0
        total_output = 0
        resp = None

        for _turn in range(max_turns):
            try:
                resp = await llm.amessages_create(
                    messages=messages, model=model, tools=tools, system=system,
                )
            except Exception as e:
                logger.exception("astream: LLM call failed")
                yield {"type": "error", "message": f"LLM call failed: {e}"}
                return

            total_input += resp.input_tokens
            total_output += resp.output_tokens
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses or resp.stop_reason == "end_turn":
                yield {"type": "response", "content": resp.content, "stop_reason": resp.stop_reason,
                       "input_tokens": total_input, "output_tokens": total_output}
                return

            messages.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": b.tool_use_id, "name": b.tool_name, "input": b.tool_input}
                for b in tool_uses
            ]})
            tool_results = []
            for tu in tool_uses:
                handler = tool_handlers.get(tu.tool_name)
                result, error = None, None
                if handler:
                    try:
                        import inspect
                        if inspect.iscoroutinefunction(handler):
                            result = await handler(**(tu.tool_input or {}))
                        else:
                            result = handler(**(tu.tool_input or {}))
                    except Exception as e:
                        error = str(e)
                else:
                    error = f"Unknown tool: {tu.tool_name}"
                yield {"type": "tool_call", "name": tu.tool_name, "input": tu.tool_input, "result": result, "error": error}
                content = json.dumps({"error": error}) if error else (json.dumps(result, default=str) if not isinstance(result, str) else result)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.tool_use_id, "content": content, **({"is_error": True} if error else {})})
            messages.append({"role": "user", "content": tool_results})

        yield {"type": "response", "content": resp.content if resp else [], "stop_reason": "max_turns",
               "input_tokens": total_input, "output_tokens": total_output}

    # ── Sync native tool loop (GC) ──

    def run(
        self,
        prompt: str,
        model: str,
        tools: list[ToolDef],
        max_turns: int = 5,
    ) -> LLMResponse:
        """Sync multi-turn tool loop with ToolDef-based tools."""
        llm = self._get_llm()
        api_tools = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        tool_handlers = {t.name: t.handler for t in tools}
        messages: list[dict] = [{"role": "user", "content": prompt}]
        total_input = 0
        total_output = 0
        final_text = ""

        for turn in range(max_turns):
            logger.debug("run turn=%d model=%s tools=%d", turn, model, len(api_tools))
            kwargs: dict = {"model": model, "max_tokens": 16384, "messages": messages, "tools": api_tools}
            if "opus-4-6" in model or "sonnet-4-6" in model:
                kwargs["thinking"] = {"type": "adaptive"}
            response = llm._sync.messages.create(**kwargs)
            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]
            if text_blocks:
                final_text = text_blocks[-1].text
            if not tool_uses or response.stop_reason == "end_turn":
                break
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": self._exec_tools(tool_uses, tool_handlers)})

        return LLMResponse(text=final_text, input_tokens=total_input, output_tokens=total_output)

    @staticmethod
    def _exec_tools(tool_uses: list, tool_handlers: dict) -> list[dict]:
        results = []
        for tu in tool_uses:
            handler = tool_handlers.get(tu.name)
            if handler:
                try:
                    result = handler(**tu.input)
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result, default=str)})
                except Exception as e:
                    logger.warning("Tool %s failed: %s", tu.name, e)
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps({"error": str(e)}), "is_error": True})
            else:
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps({"error": f"Unknown: {tu.name}"}), "is_error": True})
        return results
