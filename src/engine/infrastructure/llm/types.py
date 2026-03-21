"""LLM response types and tool definitions."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


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
