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
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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


class AgentSDKClient(LLMClient):
    """Uses Claude Agent SDK — works with OAuth token or logged-in CLI session.

    Auth priority:
    1. Explicit OAuth token → CLAUDE_CODE_OAUTH_TOKEN env var
    2. No token → relies on CLI's own session (~/.claude.json)
    """

    def __init__(self, auth_token: str = ""):
        self._auth_token = auth_token

    def complete(self, prompt: str, model: str) -> LLMResponse:
        return asyncio.run(self.acomplete(prompt, model))

    async def acomplete(self, prompt: str, model: str) -> LLMResponse:
        from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

        # Prevent nesting check when running inside Claude Code dev environment
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        if self._auth_token:
            # OAuth token: set CLAUDE_CODE_OAUTH_TOKEN, clear conflicting vars
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self._auth_token
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
            env.pop("ANTHROPIC_API_KEY", None)

        result_text = ""
        cost_usd = None
        async for msg in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                model=model,
                max_turns=1,
                permission_mode="bypassPermissions",
                tools=[],
                env=env,
            ),
        ):
            if isinstance(msg, ResultMessage):
                result_text = msg.result or ""
                cost_usd = msg.total_cost_usd

        return LLMResponse(text=result_text, cost_usd=cost_usd)


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
