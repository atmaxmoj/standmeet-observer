"""AgentService — agentic multi-turn tool interactions.

Single entry point for any code that needs multi-turn LLM + tools.
Consumers: distill, compose, gc, chat.

Usage:
    agent = AgentService(llm)
    result = agent.run(prompt, tools, session)           # sync, with ToolDef
    result = await agent.arun(messages, tools, system)   # async, with API tool dicts
    result = agent.run_with_mcp(prompt, mcp_server, ...) # sync, Agent SDK + MCP
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
    """Result from an agentic run."""
    result_text: str
    cost_usd: float
    input_tokens: int
    output_tokens: int


class AgentService:
    """Multi-turn tool interactions on top of LLMClient."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    # ── Sync tool loop (GC, distill one-shot with tools) ──

    def run(
        self,
        prompt: str,
        model: str,
        tools: list[ToolDef],
        max_turns: int = 5,
    ) -> LLMResponse:
        """Sync multi-turn tool loop. Works with any LLMClient."""
        if hasattr(self.llm, '_sync'):
            return self._run_native(prompt, model, tools, max_turns)
        return self._run_text(prompt, model, tools, max_turns)

    # ── Async streaming tool loop (chat) ──

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

        tool_handlers values can be sync or async callables.

        For DirectAPIClient: uses native amessages_create with tool_use blocks.
        For AgentSDKClient (OAuth): wraps tools as MCP server, uses Agent SDK.

        Yields dicts with "type" key:
          {"type": "tool_call", "name": ..., "input": ..., "result": ...}
          {"type": "response", "content": [...], "stop_reason": ..., "input_tokens": ..., "output_tokens": ...}
          {"type": "error", "message": ...}
        """
        # Always use native path. For AgentSDKClient (OAuth), amessages_create
        # puts tools in prompt text — LLM may not use them (known limitation).
        # MCP path doesn't work for chat because FastMCP can't wrap async handlers.
        async for event in self._astream_native(messages, model, tools, tool_handlers, system, max_turns):
            yield event

    async def _astream_native(self, messages, model, tools, tool_handlers, system, max_turns):
        """Native API path — uses amessages_create with tool_use blocks."""
        logger.info("astream: using native API path (%d tools)", len(tools))
        total_input = 0
        total_output = 0
        resp = None

        for _turn in range(max_turns):
            try:
                resp = await self.llm.amessages_create(
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

    async def _astream_via_mcp(self, messages, model, tools, tool_handlers, system, max_turns):
        """OAuth path — wraps tools as MCP server, runs via Agent SDK."""
        logger.info("astream: using MCP/Agent SDK path (%d tools)", len(tools))
        from mcp.server.fastmcp import FastMCP

        # Build MCP server from tool definitions
        mcp = FastMCP("chat-tools")
        for tool_def in tools:
            name = tool_def["name"]
            handler = tool_handlers.get(name)
            if handler:
                # Register as MCP tool
                mcp.tool(name=name, description=tool_def.get("description", ""))(handler)

        # Build prompt from messages
        parts = []
        if system:
            parts.append(system)
        for m in messages:
            content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
            parts.append(f"[{m['role']}]: {content}")
        prompt = "\n\n".join(parts)

        try:
            from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions, ResultMessage

            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
            if token:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = token
                env.pop("ANTHROPIC_AUTH_TOKEN", None)
                env.pop("ANTHROPIC_API_KEY", None)

            result_text = ""
            usage = {}
            async for msg in sdk_query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    model=model,
                    max_turns=max_turns,
                    permission_mode="bypassPermissions",
                    mcp_servers={"chat": {"type": "sdk", "name": "chat-tools", "instance": mcp._mcp_server}},
                    env=env,
                ),
            ):
                if isinstance(msg, ResultMessage):
                    result_text = msg.result or ""
                    usage = msg.usage or {}

            from engine.llm.types import ContentBlock
            yield {
                "type": "response",
                "content": [ContentBlock(type="text", text=result_text)],
                "stop_reason": "end_turn",
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            }
        except Exception as e:
            logger.exception("astream_via_mcp failed")
            yield {"type": "error", "message": f"Agent SDK chat failed: {e}"}

    # ── Agent SDK + MCP (agentic distill/compose) ──

    def run_with_mcp(
        self,
        prompt: str,
        mcp_server: FastMCP,
        mcp_name: str,
        stage: str,
        session: Session,
        model: str = "",
        max_turns: int = 15,
    ) -> AgentResult:
        """Multi-turn agentic with MCP tools via Agent SDK.

        Only method that uses Agent SDK — needed for MCP tool integration.
        """
        from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions, ResultMessage
        from engine.config import MODEL_DEEP

        if not model:
            model = MODEL_DEEP

        logger.info("%s: starting agentic run", stage)

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

    # ── Private: native API tool loop ──

    def _run_native(self, prompt: str, model: str, tools: list[ToolDef], max_turns: int) -> LLMResponse:
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
            messages.append({"role": "user", "content": self._exec_tools(tool_uses, tool_handlers)})

        return LLMResponse(text=final_text, input_tokens=total_input, output_tokens=total_output)

    def _run_text(self, prompt: str, model: str, tools: list[ToolDef], max_turns: int) -> LLMResponse:
        """Text-based tool loop for AgentSDKClient (OAuth)."""
        tool_handlers = {t.name: t.handler for t in tools}
        tool_desc = "\n".join(f"- {t.name}: {t.description}" for t in tools)
        conversation = [f"{prompt}\n\nAvailable tools:\n{tool_desc}\n\nTo call a tool: <tool_call>{{\"name\":\"...\",\"input\":{{...}}}}</tool_call>"]
        total_input = 0
        total_output = 0
        final_text = ""

        for turn in range(max_turns):
            resp = self.llm.complete("\n\n".join(conversation), model)
            total_input += resp.input_tokens
            total_output += resp.output_tokens
            final_text = resp.text
            if "<tool_call>" not in resp.text:
                break
            import re
            calls = re.findall(r'<tool_call>(.*?)</tool_call>', resp.text, re.DOTALL)
            if not calls:
                break
            conversation.append(resp.text)
            results = []
            for call_str in calls:
                try:
                    call = json.loads(call_str)
                    handler = tool_handlers.get(call["name"])
                    result = handler(**call.get("input", {})) if handler else {"error": f"Unknown: {call['name']}"}
                    results.append(f"[Tool {call['name']}: {json.dumps(result, default=str)[:2000]}]")
                except Exception as e:
                    results.append(f"[Tool error: {e}]")
            conversation.append("\n".join(results))

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
