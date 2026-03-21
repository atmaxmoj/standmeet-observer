"""LLM client abstract base.

Pure LLM capability — text completion and structured message API.
No Agent SDK, no tool orchestration.
"""

from abc import ABC, abstractmethod

from engine.infrastructure.llm.types import LLMResponse, MessageResponse


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
