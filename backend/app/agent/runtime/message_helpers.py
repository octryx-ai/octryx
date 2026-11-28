"""Message and tool filtering helpers used by the agent engine."""

from __future__ import annotations

from app.agent.runtime.engine_limits import APPROX_CHARS_PER_TOKEN
from app.agent.runtime.types import ChatMessage
from app.services.token_estimation import estimate_message_tokens


def _truncate_for_model(value: str, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _estimate_message_tokens(messages: list[ChatMessage]) -> int:
    return estimate_message_tokens(messages, approx_chars_per_token=APPROX_CHARS_PER_TOKEN)


def _trim_messages_to_budget(messages: list[ChatMessage], token_budget: int) -> list[ChatMessage]:
    if token_budget <= 0 or len(messages) <= 2:
        return messages

    trimmed = [dict(message) for message in messages]
    # The leading contiguous system block carries the governance contracts
    # (agent definition, execution contract, workflow contract) and the last
    # user message carries the actual task. Dropping either produced live
    # provider rejections (Bedrock: "conversation must start with a user
    # message") and a model with no task — both are non-droppable.
    head_end = 0
    while head_end < len(trimmed) - 1 and str(trimmed[head_end].get("role") or "").strip().lower() == "system":
        head_end += 1
    head = trimmed[:head_end]
    middle_messages = trimmed[head_end:-1]
    chunks: list[list[ChatMessage]] = []
    index = 0
    while index < len(middle_messages):
        message = middle_messages[index]
        role = str(message.get("role") or "").strip().lower()
        if role == "tool" and chunks:
            chunks[-1].append(message)
            index += 1
            continue
        if role == "assistant" and message.get("tool_calls"):
            chunk = [message]
            index += 1
            while index < len(middle_messages):
                next_message = middle_messages[index]
                next_role = str(next_message.get("role") or "").strip().lower()
                if next_role != "tool":
                    break
                chunk.append(next_message)
                index += 1
            chunks.append(chunk)
            continue
        chunks.append([message])
        index += 1

    # Protect the last user chunk only when dropping it would leave the
    # request without ANY user message (agent runs where the task prompt sits
    # mid-history). When the final message is itself the current user request,
    # older user messages stay droppable.
    last_user_chunk_index = -1
    if str(trimmed[-1].get("role") or "").strip().lower() != "user":
        for chunk_index in range(len(chunks) - 1, -1, -1):
            if any(str(item.get("role") or "").strip().lower() == "user" for item in chunks[chunk_index]):
                last_user_chunk_index = chunk_index
                break

    def _rebuilt() -> list[ChatMessage]:
        return [*head, *(item for chunk in chunks for item in chunk), trimmed[-1]]

    drop_index = 0
    while len(chunks) > 1 and _estimate_message_tokens(_rebuilt()) > token_budget:
        if drop_index == last_user_chunk_index:
            drop_index += 1
            if drop_index >= len(chunks):
                break
            continue
        chunks.pop(drop_index)
        if drop_index < last_user_chunk_index:
            last_user_chunk_index -= 1
        if drop_index >= len(chunks):
            break

    trimmed = _rebuilt()

    if _estimate_message_tokens(trimmed) <= token_budget:
        return trimmed

    system_message = dict(trimmed[0])
    final_message = dict(trimmed[-1])
    system_content = str(system_message.get("content") or "")
    final_content = str(final_message.get("content") or "")

    max_chars = max(2000, token_budget * APPROX_CHARS_PER_TOKEN)
    reserved_for_user = min(len(final_content), max_chars // 3)
    reserved_for_system = max(800, max_chars - reserved_for_user - 200)

    if len(system_content) > reserved_for_system:
        system_message["content"] = _truncate_for_model(system_content, reserved_for_system)
    if len(final_content) > max_chars // 2:
        final_message["content"] = _truncate_for_model(final_content, max_chars // 2)

    trimmed[0] = system_message
    trimmed[-1] = final_message
    return trimmed


