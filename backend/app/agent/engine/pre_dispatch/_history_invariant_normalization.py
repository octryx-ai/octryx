"""Canonical pre-dispatch history invariant audit and normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...core.types import ChatMessage


@dataclass(frozen=True)
class HistoryInvariantFinding:
    """A concrete invariant issue detected in pre-dispatch history."""

    code: str
    message_index: int
    detail: str
    tool_call_id: str | None = None


@dataclass(frozen=True)
class AssistantToolCallRewrite:
    """How one assistant message should be rewritten for canonical dispatch."""

    message_index: int
    keep_tool_call_indexes: tuple[int, ...]
    drop_tool_call_indexes: tuple[int, ...]
    kept_tool_call_ids: tuple[str, ...]
    dropped_tool_call_ids: tuple[str, ...]
    drop_tool_calls_field: bool


@dataclass(frozen=True)
class PreDispatchHistoryNormalizationPlan:
    """Bounded normalization plan for dispatch-ready message history."""

    findings: tuple[HistoryInvariantFinding, ...]
    assistant_rewrites: tuple[AssistantToolCallRewrite, ...]
    drop_message_indexes: tuple[int, ...]
    canonical_tool_call_ids: tuple[str, ...]
    valid_tool_result_ids: tuple[str, ...]
    dangling_assistant_tool_call_ids: tuple[str, ...]
    orphan_tool_result_ids: tuple[str, ...]
    requires_normalization: bool


@dataclass(frozen=True)
class _AssistantToolCallRef:
    message_index: int
    tool_call_index: int
    tool_call_id: str


def _normalized_tool_call_id(value: Any) -> str:
    return str(value or "").strip()


def plan_pre_dispatch_history_normalization(messages: list[ChatMessage]) -> PreDispatchHistoryNormalizationPlan:
    findings: list[HistoryInvariantFinding] = []
    drop_message_indexes: set[int] = set()

    first_assistant_call_by_id: dict[str, _AssistantToolCallRef] = {}
    assistant_call_order: list[str] = []
    assistant_drop_indexes_by_message: dict[int, set[int]] = {}
    valid_tool_result_ids: list[str] = []
    valid_tool_result_id_set: set[str] = set()
    orphan_tool_result_ids: list[str] = []

    for message_index, raw_message in enumerate(messages):
        message = raw_message if isinstance(raw_message, dict) else {}
        role = str(message.get("role") or "").strip().lower()

        if role == "assistant":
            if not str(message.get("content") or "").strip() and not list(message.get("tool_calls") or []):
                drop_message_indexes.add(message_index)
                findings.append(
                    HistoryInvariantFinding(
                        code="empty_assistant_message",
                        message_index=message_index,
                        detail="Empty assistant messages should not be dispatched to runtimes.",
                    )
                )
                continue
            for tool_call_index, tool_call in enumerate(list(message.get("tool_calls") or [])):
                tool_call_id = _normalized_tool_call_id((tool_call or {}).get("id"))
                if not tool_call_id:
                    assistant_drop_indexes_by_message.setdefault(message_index, set()).add(tool_call_index)
                    findings.append(
                        HistoryInvariantFinding(
                            code="assistant_tool_call_missing_id",
                            message_index=message_index,
                            detail="Assistant tool calls must have a non-empty id before dispatch.",
                        )
                    )
                    continue
                if tool_call_id in first_assistant_call_by_id:
                    assistant_drop_indexes_by_message.setdefault(message_index, set()).add(tool_call_index)
                    findings.append(
                        HistoryInvariantFinding(
                            code="duplicate_assistant_tool_call_id",
                            message_index=message_index,
                            tool_call_id=tool_call_id,
                            detail="Assistant tool call ids must be unique across dispatch history.",
                        )
                    )
                    continue
                first_assistant_call_by_id[tool_call_id] = _AssistantToolCallRef(
                    message_index=message_index,
                    tool_call_index=tool_call_index,
                    tool_call_id=tool_call_id,
                )
                assistant_call_order.append(tool_call_id)
            continue

        if role != "tool":
            continue

        tool_call_id = _normalized_tool_call_id(message.get("tool_call_id"))
        if not tool_call_id:
            drop_message_indexes.add(message_index)
            findings.append(
                HistoryInvariantFinding(
                    code="tool_result_missing_id",
                    message_index=message_index,
                    detail="Tool result messages must have a non-empty tool_call_id before dispatch.",
                )
            )
            continue
        if tool_call_id not in first_assistant_call_by_id:
            drop_message_indexes.add(message_index)
            orphan_tool_result_ids.append(tool_call_id)
            findings.append(
                HistoryInvariantFinding(
                    code="orphan_tool_result",
                    message_index=message_index,
                    tool_call_id=tool_call_id,
                    detail="Tool result messages must reference an earlier assistant tool call id.",
                )
            )
            continue
        if tool_call_id in valid_tool_result_id_set:
            drop_message_indexes.add(message_index)
            findings.append(
                HistoryInvariantFinding(
                    code="duplicate_tool_result",
                    message_index=message_index,
                    tool_call_id=tool_call_id,
                    detail="Canonical dispatch history keeps at most one tool result per tool call id.",
                )
            )
            continue

        valid_tool_result_ids.append(tool_call_id)
        valid_tool_result_id_set.add(tool_call_id)

    dangling_assistant_tool_call_ids: list[str] = []
    for tool_call_id in assistant_call_order:
        if tool_call_id in valid_tool_result_id_set:
            continue
        ref = first_assistant_call_by_id[tool_call_id]
        assistant_drop_indexes_by_message.setdefault(ref.message_index, set()).add(ref.tool_call_index)
        dangling_assistant_tool_call_ids.append(tool_call_id)
        findings.append(
            HistoryInvariantFinding(
                code="dangling_assistant_tool_call",
                message_index=ref.message_index,
                tool_call_id=tool_call_id,
                detail="Assistant tool calls without a matching tool result should be removed before dispatch.",
            )
        )

    assistant_rewrites: list[AssistantToolCallRewrite] = []
    for message_index, raw_message in enumerate(messages):
        message = raw_message if isinstance(raw_message, dict) else {}
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue
        tool_calls = list(message.get("tool_calls") or [])
        if not tool_calls:
            continue

        drop_indexes = assistant_drop_indexes_by_message.get(message_index, set())
        keep_indexes = tuple(index for index in range(len(tool_calls)) if index not in drop_indexes)
        if not drop_indexes:
            continue

        kept_tool_call_ids = tuple(
            _normalized_tool_call_id((tool_calls[index] or {}).get("id"))
            for index in keep_indexes
            if _normalized_tool_call_id((tool_calls[index] or {}).get("id"))
        )
        dropped_tool_call_ids = tuple(
            tool_call_id
            for index in sorted(drop_indexes)
            if (tool_call_id := _normalized_tool_call_id((tool_calls[index] or {}).get("id")))
        )
        assistant_rewrites.append(
            AssistantToolCallRewrite(
                message_index=message_index,
                keep_tool_call_indexes=keep_indexes,
                drop_tool_call_indexes=tuple(sorted(drop_indexes)),
                kept_tool_call_ids=kept_tool_call_ids,
                dropped_tool_call_ids=dropped_tool_call_ids,
                drop_tool_calls_field=not keep_indexes,
            )
        )
        if not keep_indexes and not str(message.get("content") or "").strip():
            drop_message_indexes.add(message_index)
            findings.append(
                HistoryInvariantFinding(
                    code="empty_assistant_message",
                    message_index=message_index,
                    detail="Assistant messages left empty after dropping dangling tool calls should not be dispatched.",
                )
            )

    has_dispatchable_user_message = any(
        str((message if isinstance(message, dict) else {}).get("role") or "").strip().lower() == "user"
        for message in messages
    )
    if has_dispatchable_user_message:
        for message_index, raw_message in enumerate(messages):
            if message_index in drop_message_indexes:
                continue
            message = raw_message if isinstance(raw_message, dict) else {}
            role = str(message.get("role") or "").strip().lower()
            if role == "system":
                continue
            if role == "user":
                break
            drop_message_indexes.add(message_index)
            findings.append(
                HistoryInvariantFinding(
                    code="leading_non_user_message",
                    message_index=message_index,
                    detail="Runtime conversations must start with a user message after system context.",
                )
            )

    canonical_tool_call_ids = tuple(
        tool_call_id for tool_call_id in assistant_call_order if tool_call_id in valid_tool_result_id_set
    )
    requires_normalization = bool(findings or assistant_rewrites or drop_message_indexes)
    return PreDispatchHistoryNormalizationPlan(
        findings=tuple(findings),
        assistant_rewrites=tuple(assistant_rewrites),
        drop_message_indexes=tuple(sorted(drop_message_indexes)),
        canonical_tool_call_ids=canonical_tool_call_ids,
        valid_tool_result_ids=tuple(valid_tool_result_ids),
        dangling_assistant_tool_call_ids=tuple(dangling_assistant_tool_call_ids),
        orphan_tool_result_ids=tuple(orphan_tool_result_ids),
        requires_normalization=requires_normalization,
    )


def normalize_pre_dispatch_history(
    messages: list[ChatMessage],
) -> tuple[list[ChatMessage], PreDispatchHistoryNormalizationPlan]:
    """Normalize dispatch history according to the canonical invariant plan."""

    plan = plan_pre_dispatch_history_normalization(messages)
    if not plan.requires_normalization:
        return [dict(message) for message in messages], plan

    rewrites = {rewrite.message_index: rewrite for rewrite in plan.assistant_rewrites}
    dropped_message_indexes = set(plan.drop_message_indexes)
    normalized_messages: list[ChatMessage] = []

    for message_index, raw_message in enumerate(messages):
        if message_index in dropped_message_indexes:
            continue

        current_message = dict(raw_message)
        rewrite = rewrites.get(message_index)
        if rewrite is not None:
            tool_calls = list(current_message.get("tool_calls") or [])
            if rewrite.drop_tool_calls_field:
                current_message.pop("tool_calls", None)
            else:
                current_message["tool_calls"] = [tool_calls[index] for index in rewrite.keep_tool_call_indexes]
        normalized_messages.append(current_message)

    return normalized_messages, plan
