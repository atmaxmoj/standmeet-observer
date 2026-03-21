"""OpenAI-compatible LLM client — any OpenAI-compatible API."""

from engine.infrastructure.llm.client import LLMClient
from engine.infrastructure.llm.types import LLMResponse


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
