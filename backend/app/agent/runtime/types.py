"""Typed dataclasses and TypedDicts for the agent layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict


class ToolCallFunction(TypedDict):
    name: str
    arguments: str  # JSON-encoded string


class ToolCall(TypedDict, total=False):
    id: str
    type: Literal["function"]
    function: ToolCallFunction


class ChatMessage(TypedDict, total=False):
    """A single message in the LLM conversation history."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[Any]  # str or provider-specific content blocks
    cache_scope: Literal["stable", "volatile"]  # optional prompt-cache boundary hint for providers
    content_trust: Literal["platform_instruction", "authored"]  # system text trust (content_security.message_trust)
    tool_calls: list[ToolCall]  # only on assistant messages
    tool_call_id: str  # only on tool-result messages
    name: str  # optional tool/function name



class ToolParameterSchema(TypedDict, total=False):
    type: str
    properties: dict[str, Any]
    required: list[str]
    description: str


class ToolFunction(TypedDict, total=False):
    name: str
    description: str
    parameters: ToolParameterSchema


class ToolDefinition(TypedDict, total=False):
    """OpenAI-compatible tool definition."""

    type: Literal["function"]
    function: ToolFunction



class RuntimeTarget(TypedDict, total=False):
    """A configured LLM runtime target (provider + model)."""

    id: str
    provider_name: str
    model: str
    is_primary: bool
    is_active: bool
    direction: str
    thinking_level: str | None
    max_tokens: int | None



class TokenUsage(TypedDict, total=False):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class AgentResponse(TypedDict, total=False):
    """Normalised response returned by any provider runtime."""

    content: str | None
    tool_calls: list[ToolCall]
    model: str
    usage: TokenUsage
    thinking: str | None
    finish_reason: str | None



class ContextSnapshot(TypedDict, total=False):
    """Immutable snapshot of agent context attached to each turn trace."""

    system_prompt: str
    memory_prompt: str
    skills_prompt: str
    tool_names: list[str]
    runtime_id: str | None
    model: str | None
    token_budget: int | None
    tier: str | None



class RuntimeSettings(TypedDict, total=False):
    """Flat dict of agent-level runtime settings from system config."""

    default_model: str | None
    fallback_model: str | None
    max_tool_calls_per_turn: int | None
    max_completion_tokens: int | None
    approx_chars_per_token: int | None



@dataclass(frozen=True)
class ToolCallResult:
    tool_call_id: str
    tool_name: str
    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
