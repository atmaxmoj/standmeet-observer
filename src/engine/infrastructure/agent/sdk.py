"""Agent SDK wrapper — encapsulates Claude Agent SDK (OAuth path).

Provides text completion and MCP-based multi-turn agentic runs.
All Agent SDK / Claude Code CLI specifics are contained here.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.infrastructure.llm.types import LLMResponse

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


def _build_env(auth_token: str) -> dict:
    """Build env dict for Agent SDK subprocess with OAuth token."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    if auth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = auth_token
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env.pop("ANTHROPIC_API_KEY", None)
    return env


def complete(prompt: str, model: str, auth_token: str) -> LLMResponse:
    """Single-turn text completion via Agent SDK. Sync."""
    return asyncio.run(acomplete(prompt, model, auth_token))


async def acomplete(prompt: str, model: str, auth_token: str) -> LLMResponse:
    """Single-turn text completion via Agent SDK. Async."""
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
            env=_build_env(auth_token),
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


def run_with_mcp(
    prompt: str,
    mcp_server: FastMCP,
    mcp_name: str,
    stage: str,
    session: Session,
    auth_token: str,
    model: str = "",
    max_turns: int = 40,
) -> AgentResult:
    """Multi-turn agentic run with MCP tools via Agent SDK."""
    from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions, ResultMessage
    from engine.config import MODEL_DEEP

    if not model:
        model = MODEL_DEEP

    logger.info("%s: starting agentic run", stage)

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
                env=_build_env(auth_token),
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

    from engine.infrastructure.persistence.sync_db import SyncDB
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
