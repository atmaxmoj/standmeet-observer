"""LLM client adapter — abstracts over different auth methods.

Four backends:
- DirectAPI: uses anthropic SDK directly (requires API key)
- AgentSDK: uses Claude Agent SDK (OAuth token or logged-in CLI session)
- OpenAIClient: uses openai SDK (any OpenAI-compatible API)

Priority (first match wins):
1. OPENAI_BASE_URL set         → OpenAI-compatible API
2. ANTHROPIC_API_KEY set       → DirectAPI (per-token billing)
3. ANTHROPIC_AUTH_TOKEN set    → AgentSDK with OAuth token (subscription billing)
4. Neither                     → AgentSDK with CLI session (subscription billing)
"""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolDef:
    """Tool definition for agent tool-use loop."""
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Any]


@dataclass
class ContentBlock:
    """A block in a model response — text or tool_use."""
    type: str  # "text" or "tool_use"
    text: str = ""
    tool_name: str = ""
    tool_input: dict | None = None
    tool_use_id: str = ""


@dataclass
class MessageResponse:
    """Response from a single amessages_create call."""
    content: list[ContentBlock]
    stop_reason: str  # "end_turn" or "tool_use"
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    """Unified response from any LLM backend."""
    text: str
    cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(ABC):
    """Abstract LLM client interface."""

    @abstractmethod
    def complete(self, prompt: str, model: str) -> LLMResponse:
        """Send a prompt, get a text response. Synchronous."""
        ...

    @abstractmethod
    async def acomplete(self, prompt: str, model: str) -> LLMResponse:
        """Async version of complete."""
        ...

    async def amessages_create(
        self,
        *,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        system: str = "",
        max_tokens: int = 4096,
    ) -> MessageResponse:
        """Single async API call with messages, tools, and system prompt.

        Returns structured content blocks (text + tool_use).
        Subclasses implement this; the tool-use loop is managed by callers.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support amessages_create"
        )

    def complete_with_tools(
        self,
        prompt: str,
        model: str,
        tools: list[ToolDef],
        max_turns: int = 5,
    ) -> LLMResponse:
        """Multi-turn tool-use loop. Default raises NotImplementedError."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support tool use"
        )


def _serialize_messages_to_prompt(
    messages: list[dict],
    tools: list[dict] | None = None,
    system: str = "",
) -> str:
    """Serialize structured messages + tools into a text prompt for text-only backends."""
    parts: list[str] = []
    if system:
        parts.append(f"<system>\n{system}\n</system>\n")
    if tools:
        tool_desc = json.dumps(tools, indent=2)
        parts.append(
            f"<available_tools>\n{tool_desc}\n</available_tools>\n\n"
            "When you need to call a tool, respond with ONLY a JSON block in this exact format:\n"
            '<tool_call>\n{"name": "tool_name", "input": {...}}\n</tool_call>\n\n'
            "When you have your final answer, respond with plain text (no tool_call tags).\n"
        )
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(f"<{role}>\n{content}\n</{role}>")
        elif isinstance(content, list):
            # Tool results or multi-block content
            texts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_result":
                        texts.append(f"[Tool result: {block.get('content', '')}]")
                    elif block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    else:
                        texts.append(json.dumps(block, default=str))
                else:
                    texts.append(str(block))
            parts.append(f"<{role}>\n{''.join(texts)}\n</{role}>")
    return "\n".join(parts)


def _parse_tool_calls(text: str) -> list[ContentBlock]:
    """Parse <tool_call> blocks from text response. Returns ContentBlocks."""
    import re
    blocks: list[ContentBlock] = []
    pattern = r"<tool_call>\s*(\{.*?\})\s*</tool_call>"
    matches = re.findall(pattern, text, re.DOTALL)
    for i, match in enumerate(matches):
        try:
            parsed = json.loads(match)
            blocks.append(ContentBlock(
                type="tool_use",
                tool_name=parsed["name"],
                tool_input=parsed.get("input", {}),
                tool_use_id=f"text_tool_{i}",
            ))
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse tool_call: %s", match)
    # Also extract non-tool-call text
    clean = re.sub(pattern, "", text, flags=re.DOTALL).strip()
    if clean:
        blocks.insert(0, ContentBlock(type="text", text=clean))
    return blocks


class AgentSDKClient(LLMClient):
    """Uses Claude Agent SDK — works with OAuth token or logged-in CLI session.

    Auth priority:
    1. Explicit OAuth token → CLAUDE_CODE_OAUTH_TOKEN env var
    2. No token → relies on CLI's own session (~/.claude.json)
    """

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

    def complete_with_tools(
        self,
        prompt: str,
        model: str,
        tools: list[ToolDef],
        max_turns: int = 5,
    ) -> LLMResponse:
        """Multi-turn tool-use loop via text-based <tool_call> parsing."""
        api_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        tool_handlers = {t.name: t.handler for t in tools}

        messages: list[dict] = [{"role": "user", "content": prompt}]
        total_input = 0
        total_output = 0
        final_text = ""

        for _turn in range(max_turns):
            text_prompt = _serialize_messages_to_prompt(messages, api_tools)
            resp = self.complete(text_prompt, model)
            total_input += resp.input_tokens
            total_output += resp.output_tokens

            blocks = _parse_tool_calls(resp.text)
            text_blocks = [b for b in blocks if b.type == "text"]
            tool_uses = [b for b in blocks if b.type == "tool_use"]

            if text_blocks:
                final_text = text_blocks[-1].text

            if not tool_uses:
                break

            messages.append({"role": "assistant", "content": resp.text})
            tool_results = []
            for tu in tool_uses:
                handler = tool_handlers.get(tu.tool_name)
                if handler:
                    try:
                        result = handler(**(tu.tool_input or {}))
                        tool_results.append(
                            f"[Tool result for {tu.tool_name}: "
                            f"{json.dumps(result, default=str)[:2000]}]"
                        )
                    except Exception as e:
                        logger.warning("Tool %s failed: %s", tu.tool_name, e)
                        tool_results.append(f"[Tool {tu.tool_name} error: {e}]")
                else:
                    tool_results.append(f"[Unknown tool: {tu.tool_name}]")
            messages.append({"role": "user", "content": "\n".join(tool_results)})

        return LLMResponse(
            text=final_text,
            input_tokens=total_input,
            output_tokens=total_output,
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
        """Serialize to prompt, call query(), parse tool calls from response."""
        prompt = _serialize_messages_to_prompt(messages, tools, system)
        resp = await self.acomplete(prompt, model)
        blocks = _parse_tool_calls(resp.text) if tools else [
            ContentBlock(type="text", text=resp.text)
        ]
        has_tool_use = any(b.type == "tool_use" for b in blocks)
        return MessageResponse(
            content=blocks,
            stop_reason="tool_use" if has_tool_use else "end_turn",
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )


class DirectAPIClient(LLMClient):
    """Uses anthropic SDK directly — requires API key (per-token billing)."""

    def __init__(self, api_key: str):
        import anthropic
        self._sync = anthropic.Anthropic(api_key=api_key)
        self._async = anthropic.AsyncAnthropic(api_key=api_key)

    def complete(self, prompt: str, model: str) -> LLMResponse:
        response = self._sync.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        usage = response.usage
        return LLMResponse(
            text=raw,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    async def acomplete(self, prompt: str, model: str) -> LLMResponse:
        response = await self._async.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        usage = response.usage
        return LLMResponse(
            text=raw,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
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
        """Native Anthropic Messages API call with tool support."""
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if system:
            kwargs["system"] = system

        response = await self._async.messages.create(**kwargs)
        blocks = []
        for b in response.content:
            if b.type == "text":
                blocks.append(ContentBlock(type="text", text=b.text))
            elif b.type == "tool_use":
                blocks.append(ContentBlock(
                    type="tool_use",
                    tool_name=b.name,
                    tool_input=b.input,
                    tool_use_id=b.id,
                ))
        return MessageResponse(
            content=blocks,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def complete_with_tools(
        self,
        prompt: str,
        model: str,
        tools: list[ToolDef],
        max_turns: int = 5,
    ) -> LLMResponse:
        """Multi-turn tool-use loop using Anthropic SDK."""
        # Build tool definitions for the API
        api_tools = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]
        tool_handlers = {t.name: t.handler for t in tools}

        messages = [{"role": "user", "content": prompt}]
        total_input = 0
        total_output = 0
        final_text = ""

        for turn in range(max_turns):
            response = self._sync.messages.create(
                model=model,
                max_tokens=8192,
                messages=messages,
                tools=api_tools,
            )

            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens

            # Check if the model wants to use tools
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            if text_blocks:
                final_text = text_blocks[-1].text

            if not tool_uses or response.stop_reason == "end_turn":
                # No more tool calls, we're done
                if not final_text and text_blocks:
                    final_text = text_blocks[0].text
                break

            # Execute tool calls and build tool_result messages
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tool_use in tool_uses:
                handler = tool_handlers.get(tool_use.name)
                if handler:
                    try:
                        result = handler(**tool_use.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": json.dumps(result, default=str),
                        })
                    except Exception as e:
                        logger.warning("Tool %s failed: %s", tool_use.name, e)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": json.dumps({"error": str(e)}),
                            "is_error": True,
                        })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})

        return LLMResponse(
            text=final_text,
            input_tokens=total_input,
            output_tokens=total_output,
        )


class OpenAIClient(LLMClient):
    """Uses openai SDK — any OpenAI-compatible API (ollama, vllm, openrouter, etc.)."""

    def __init__(self, api_key: str, base_url: str):
        from openai import OpenAI, AsyncOpenAI
        self._sync = OpenAI(api_key=api_key or "unused", base_url=base_url)
        self._async = AsyncOpenAI(api_key=api_key or "unused", base_url=base_url)

    def complete(self, prompt: str, model: str) -> LLMResponse:
        response = self._sync.chat.completions.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        choice = response.choices[0].message.content or ""
        usage = response.usage
        return LLMResponse(
            text=choice,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def acomplete(self, prompt: str, model: str) -> LLMResponse:
        response = await self._async.chat.completions.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        choice = response.choices[0].message.content or ""
        usage = response.usage
        return LLMResponse(
            text=choice,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


def create_client(
    api_key: str = "",
    auth_token: str = "",
    openai_api_key: str = "",
    openai_base_url: str = "",
) -> LLMClient:
    """Factory: pick the right backend based on available credentials.

    Priority:
    1. OpenAI base URL → OpenAIClient (any compatible API)
    2. Anthropic API key → DirectAPIClient (per-token billing)
    3. OAuth token → AgentSDKClient with token
    4. Neither → AgentSDKClient with CLI session (user must be logged in)
    """
    if openai_base_url:
        logger.info("Using OpenAI-compatible API (%s)", openai_base_url)
        return OpenAIClient(openai_api_key, openai_base_url)
    if api_key:
        logger.info("Using direct Anthropic API (API key)")
        return DirectAPIClient(api_key)
    if auth_token:
        logger.info("Using Claude Agent SDK (OAuth token)")
        return AgentSDKClient(auth_token)
    logger.info("Using Claude Agent SDK (CLI session)")
    return AgentSDKClient()
