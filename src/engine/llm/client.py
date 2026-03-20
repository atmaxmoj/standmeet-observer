"""LLM client abstract base + factory.

Backends:
- DirectAPI: uses anthropic SDK (API key or OAuth token)
- OpenAIClient: uses openai SDK (any OpenAI-compatible API)

Priority (first match wins):
1. OPENAI_BASE_URL set         → OpenAI-compatible API
2. ANTHROPIC_API_KEY set       → DirectAPI (per-token billing)
3. CLAUDE_CODE_OAUTH_TOKEN set → DirectAPI (OAuth, subscription billing)
"""

import logging
from abc import ABC, abstractmethod

from engine.llm.types import LLMResponse, MessageResponse

logger = logging.getLogger(__name__)


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



def create_client(
    api_key: str = "",
    auth_token: str = "",
    openai_api_key: str = "",
    openai_base_url: str = "",
) -> LLMClient:
    """Factory: pick the right backend based on available credentials."""
    if openai_base_url:
        from engine.llm.adapters.openai import OpenAIClient
        logger.info("Using OpenAI-compatible API (%s)", openai_base_url)
        return OpenAIClient(openai_api_key, openai_base_url)
    if api_key:
        from engine.llm.adapters.anthropic import DirectAPIClient
        logger.info("Using Anthropic API (API key)")
        return DirectAPIClient(api_key=api_key)
    if auth_token:
        from engine.llm.adapters.agent_sdk import AgentSDKClient
        logger.info("Using Claude Agent SDK (OAuth token)")
        return AgentSDKClient(auth_token)
    raise ValueError("No LLM credentials configured. Set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN.")
