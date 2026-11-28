"""The newest turn of an Anthropic Messages request (everything after the last assistant message), read structurally."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SYSTEM_REMINDER_PREFIX = "<system-reminder>"


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    tool_use_id: str
    name: str
    block_index: int
    input: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    tool_use_id: str
    is_error: bool
    text: str


@dataclass(frozen=True, slots=True)
class TurnDelta:
    user_texts: tuple[str, ...]
    tool_results: tuple[ToolResultBlock, ...]
    prior_tool_uses: tuple[ToolUseBlock, ...]
    inline_system_texts: tuple[str, ...] = ()

    def prompt_text(self) -> str:
        return "\n\n".join(
            text for text in self.user_texts if not text.strip().startswith(SYSTEM_REMINDER_PREFIX)
        ).strip()


def _blocks(content: Any) -> list[Mapping[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, Mapping)]
    return []


def _text_of(block: Mapping[str, Any]) -> str:
    text = block.get("text")
    return text if block.get("type") == "text" and isinstance(text, str) else ""


def tool_result_text(block: Mapping[str, Any]) -> str:
    return "\n".join(filter(None, (_text_of(item) for item in _blocks(block.get("content")))))


def system_texts(system: Any) -> list[str]:
    return [text for text in (_text_of(block) for block in _blocks(system)) if text]


def _last_assistant_index(messages: list[Any]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, Mapping) and message.get("role") == "assistant":
            return index
    return None


def _prior_tool_uses(message: Any) -> list[ToolUseBlock]:
    if not isinstance(message, Mapping):
        return []
    prior: list[ToolUseBlock] = []
    for block_index, block in enumerate(_blocks(message.get("content"))):
        if block.get("type") != "tool_use":
            continue
        raw_input = block.get("input")
        prior.append(
            ToolUseBlock(
                tool_use_id=str(block.get("id") or ""),
                name=str(block.get("name") or ""),
                block_index=block_index,
                input=raw_input if isinstance(raw_input, Mapping) else {},
            )
        )
    return prior


def newest_turn(messages: Any) -> TurnDelta:
    items = messages if isinstance(messages, list) else []
    assistant_index = _last_assistant_index(items)
    tail = items[assistant_index + 1 :] if assistant_index is not None else items
    user_texts: list[str] = []
    inline_system: list[str] = []
    results: list[ToolResultBlock] = []
    for message in tail:
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        for block in _blocks(message.get("content")):
            if role == "system":
                text = _text_of(block)
                if text:
                    inline_system.append(text)
            elif role != "user":
                continue
            elif block.get("type") == "text":
                text = _text_of(block)
                if text:
                    user_texts.append(text)
            elif block.get("type") == "tool_result":
                results.append(
                    ToolResultBlock(
                        tool_use_id=str(block.get("tool_use_id") or ""),
                        is_error=block.get("is_error") is True,
                        text=tool_result_text(block),
                    )
                )
    prior = _prior_tool_uses(items[assistant_index]) if assistant_index is not None else []
    return TurnDelta(tuple(user_texts), tuple(results), tuple(prior), tuple(inline_system))


# Earlier turns were scanned when they were new, so the conversation is not rescanned on every call.
def scanned_texts(body: Mapping[str, Any]) -> list[str]:
    delta = newest_turn(body.get("messages"))
    return [
        *system_texts(body.get("system")),
        *delta.inline_system_texts,
        *delta.user_texts,
        *(result.text for result in delta.tool_results if result.text),
    ]


__all__ = [
    "SYSTEM_REMINDER_PREFIX",
    "ToolResultBlock",
    "ToolUseBlock",
    "TurnDelta",
    "newest_turn",
    "scanned_texts",
    "system_texts",
    "tool_result_text",
]
