"""DirectAPI LLM client — uses anthropic SDK directly (per-token billing)."""

import logging
from typing import Any

from engine.llm.client import LLMClient
from engine.llm.types import ContentBlock, LLMResponse, MessageResponse

logger = logging.getLogger(__name__)


class DirectAPIClient(LLMClient):
    """Uses anthropic SDK directly — API key or OAuth token."""

    def __init__(self, api_key: str = "", auth_token: str = ""):
        import anthropic
        kwargs: dict[str, Any] = {}
        if auth_token:
            kwargs["auth_token"] = auth_token
            kwargs["api_key"] = None
        elif api_key:
            kwargs["api_key"] = api_key
        self._sync = anthropic.Anthropic(**kwargs)
        self._async = anthropic.AsyncAnthropic(**kwargs)

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

