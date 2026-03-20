"""AgentService — agentic capabilities on top of LLMClient.

Provides:
- complete_with_tools(): multi-turn tool-use loop via Anthropic API
- run_mcp(): multi-turn agentic with MCP server via Agent SDK

Consumers: distill, compose, gc pipelines.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.llm.client import LLMClient
from engine.llm.types import LLMResponse, ToolDef

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result from an agentic MCP run."""
    result_text: str
    cost_usd: float
    input_tokens: int
    output_tokens: int


class AgentService:
    """Agentic capabilities built on top of an LLMClient."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def complete_with_tools(
        self,
        prompt: str,
        model: str,
        tools: list[ToolDef],
        max_turns: int = 5,
    ) -> LLMResponse:
        """Multi-turn tool-use loop using the underlying LLM client."""
        api_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        tool_handlers = {t.name: t.handler for t in tools}

        messages: list[dict] = [{"role": "user", "content": prompt}]
        total_input = 0
        total_output = 0
        final_text = ""

        for turn in range(max_turns):
            logger.debug("complete_with_tools turn=%d model=%s tools=%d", turn, model, len(api_tools))
            kwargs: dict = {
                "model": model,
                "max_tokens": 16384,
                "messages": messages,
                "tools": api_tools,
            }
            if "opus-4-6" in model or "sonnet-4-6" in model:
                kwargs["thinking"] = {"type": "adaptive"}

            response = self.llm._sync.messages.create(**kwargs)
            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            if text_blocks:
                final_text = text_blocks[-1].text

            if not tool_uses or response.stop_reason == "end_turn":
                break

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tu in tool_uses:
                handler = tool_handlers.get(tu.name)
                if handler:
                    try:
                        result = handler(**tu.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": json.dumps(result, default=str),
                        })
                    except Exception as e:
                        logger.warning("Tool %s failed: %s", tu.name, e)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": json.dumps({"error": str(e)}),
                            "is_error": True,
                        })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps({"error": f"Unknown tool: {tu.name}"}),
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})

        return LLMResponse(
            text=final_text,
            input_tokens=total_input,
            output_tokens=total_output,
        )

    def run_mcp(
        self,
        prompt: str,
        mcp_server: "FastMCP",
        mcp_name: str,
        stage: str,
        session: "Session",
        model: str = "",
        max_turns: int = 15,
    ) -> AgentResult:
        """Run Agent SDK query() with an in-process MCP server.

        This is the only place that uses Agent SDK — for MCP tool integration.
        All other LLM calls go through self.llm directly.
        """
        from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions, ResultMessage
        from engine.config import MODEL_DEEP

        if not model:
            model = MODEL_DEEP

        logger.info("%s: starting with MCP server", stage)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
            env.pop("ANTHROPIC_API_KEY", None)

        result_text = ""
        cost_usd = None
        usage: dict = {}

        async def _run():
            nonlocal result_text, cost_usd, usage
            async for msg in sdk_query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    model=model,
                    max_turns=max_turns,
                    permission_mode="bypassPermissions",
                    mcp_servers={
                        mcp_name: {
                            "type": "sdk",
                            "name": f"{mcp_name}-tools",
                            "instance": mcp_server._mcp_server,
                        },
                    },
                    env=env,
                ),
            ):
                msg_type = type(msg).__name__
                logger.debug("%s msg: %s %s", stage, msg_type, str(msg)[:500])
                if isinstance(msg, ResultMessage):
                    result_text = msg.result or ""
                    cost_usd = msg.total_cost_usd
                    usage = msg.usage or {}

        asyncio.run(_run())

        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cost = cost_usd or 0

        from engine.storage.sync_db import SyncDB
        db = SyncDB(session)
        db.record_usage(model, stage, input_tokens, output_tokens, cost)
        db.insert_pipeline_log(stage, prompt, result_text[:5000], model, input_tokens, output_tokens, cost)

        logger.info("%s: cost=$%.4f", stage, cost)
        return AgentResult(
            result_text=result_text,
            cost_usd=cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
