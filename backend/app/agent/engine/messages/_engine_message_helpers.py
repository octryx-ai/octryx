"""Message and tool filtering helpers used by the agent engine."""

from __future__ import annotations

from ....services.prompt_catalog import render_prompt
from ....services.token_estimation import estimate_message_tokens
from ...core.context.engine_limits import APPROX_CHARS_PER_TOKEN
from ...core.guards.response_guards import (
    get_step_allowed_tools as _get_step_allowed_tools,
)
from ...core.guards.response_guards import (
    get_step_field as _get_step_field,
)
from ...core.types import ChatMessage, ToolDefinition


def _filter_tool_definitions(
    tool_definitions: list[ToolDefinition],
    allowed_tools: list[str] | None,
) -> list[ToolDefinition]:
    if not allowed_tools:
        return tool_definitions
    allowed = {tool_name.strip() for tool_name in allowed_tools if tool_name and tool_name.strip()}
    return [definition for definition in tool_definitions if definition.get("function", {}).get("name") in allowed]


def _exclude_tool_definitions(
    tool_definitions: list[ToolDefinition],
    blocked_tools: list[str] | None,
) -> list[ToolDefinition]:
    if not blocked_tools:
        return tool_definitions
    blocked = {tool_name.strip() for tool_name in blocked_tools if tool_name and tool_name.strip()}
    return [definition for definition in tool_definitions if definition.get("function", {}).get("name") not in blocked]


def _truncate_for_model(value: str, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _path_tail(value: object, *, segments: int = 6) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) <= segments:
        return normalized
    return "/".join(parts[-segments:])


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


def _build_current_step_prompt(step: dict, position: int, total_steps: int, branch_prefix: str | None = None) -> str:
    """The current-step contract (catalog keys ``tool_guard.step.*``)."""
    lines = [
        render_prompt(
            "tool_guard.step.header",
            position=position,
            total_steps=total_steps,
            step_name=step.get("name") or "-",
            step_type=_get_step_field(step, "stepType", "step_type", "-") or "-",
            instructions=step.get("instructions") or "-",
            success_criteria=_get_step_field(step, "successCriteria", "success_criteria", "-") or "-",
        )
    ]
    if branch_prefix:
        lines.append(render_prompt("tool_guard.step.branch_prefix", branch_prefix=branch_prefix))
    allowed_tools = _get_step_allowed_tools(step)
    if allowed_tools:
        lines.append(render_prompt("tool_guard.step.allowed_tools", tools=", ".join(allowed_tools)))
        lines.append(render_prompt("tool_guard.step.meta_tools"))
    else:
        lines.append(render_prompt("tool_guard.step.all_tools"))
    if str(step.get("tddCyclePhaseTitle") or "").strip():
        lines.append(
            render_prompt(
                "tool_guard.step.tdd_phase",
                phase_index=step.get("tddCyclePhaseIndex") or "?",
                phase_total=step.get("tddCyclePhaseTotal") or "?",
                phase_title=step.get("tddCyclePhaseTitle"),
            )
        )
        lines.append(
            render_prompt(
                "tool_guard.step.tdd_instructions", instructions=str(step.get("tddCyclePhaseInstructions") or "-")
            )
        )
    lines.append(render_prompt("tool_guard.step.complete"))
    return "\n".join(lines)


def _has_pending_approval_result(tool_results: list[dict]) -> bool:
    for item in tool_results:
        result = item.get("result") or {}
        if not isinstance(result, dict):
            continue
        if result.get("approval_required") and str(result.get("approval_status") or "").strip() == "pending":
            return True
    return False


def _has_pending_clarification_result(tool_results: list[dict]) -> bool:
    """Detect if any tool returned a clarification pause status."""
    for item in tool_results:
        result = item.get("result") or {}
        if not isinstance(result, dict):
            continue
        if result.get("status") == "paused" and result.get("paused"):
            return True
    return False
