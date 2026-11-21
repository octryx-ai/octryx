"""Helpers for preparing prompt messages during agent run setup."""

from __future__ import annotations

from typing import Any

from ....models import Message
from ....services.content_security.message_trust import TRUST_UNTRUSTED, system_message
from ..prompts.prompt_parts import SystemPromptParts
from ..turn.thread_context import render_thread_context_for_prompt
from ..types import ChatMessage


def split_current_turn_from_history(
    all_history: list[Message],
    current_turn_user_message_id: str,
) -> tuple[list[Message], Message | None]:
    """Exclude the in-flight user turn from persisted history when present."""

    if not current_turn_user_message_id:
        return all_history, None

    current_turn_message = None
    filtered_history: list[Message] = []
    for msg in all_history:
        if msg.id == current_turn_user_message_id and msg.role == "user":
            current_turn_message = msg
            continue
        filtered_history.append(msg)
    return filtered_history, current_turn_message


def prepend_structured_thread_context(
    *,
    summary_context_msgs: list[ChatMessage],
    context_tier: str,
    existing_thread_context: dict[str, Any],
) -> list[ChatMessage]:
    """Inject structured thread context ahead of summary messages when allowed."""

    if context_tier == "minimal" or not existing_thread_context:
        return summary_context_msgs

    structured_thread_context_prompt = render_thread_context_for_prompt(existing_thread_context)
    if not structured_thread_context_prompt:
        return summary_context_msgs

    return [
        {
            "role": "system",
            "content": "## Structured Thread Context\n" + structured_thread_context_prompt,
        },
        *summary_context_msgs,
    ]


def _system_messages(parts: SystemPromptParts) -> list[ChatMessage]:
    """One stable system message per run of sections with the same trust, then the dynamic part (untrusted).

    The content policies check each message by its trust (``content_security.message_trust``); consecutive stable
    messages form one cacheable prefix.
    """
    runs: list[tuple[str, list[str]]] = []
    for section in parts.stable_sections:
        if runs and runs[-1][0] == section.trust:
            runs[-1][1].append(section.text)
        else:
            runs.append((section.trust, [section.text]))
    messages: list[ChatMessage] = []
    for trust, texts in runs:
        text = "\n".join(texts).strip()
        if text:
            messages.append(system_message(text, trust, cache_scope="stable"))
    dynamic = parts.dynamic.strip()
    if dynamic:
        messages.append(system_message(dynamic, TRUST_UNTRUSTED, cache_scope="volatile"))
    return messages


def build_prompt_messages(
    *,
    system_prompt_parts: SystemPromptParts,
    summary_context_msgs: list[ChatMessage],
    history: list[Message],
    current_turn_content: str,
    trim_messages_to_budget: Any,
    token_budget: int,
) -> list[ChatMessage]:
    """Assemble the final prompt message list before runtime dispatch."""

    messages = _system_messages(system_prompt_parts)
    messages.extend(summary_context_msgs)
    for msg in history:
        entry: ChatMessage = {"role": msg.role, "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = msg.tool_calls
        messages.append(entry)
    messages.append({"role": "user", "content": current_turn_content})
    return trim_messages_to_budget(messages, token_budget)
