"""Generic turn trace runtime helpers.

This module provides a shared trace capture layer for agent turns so the same
trace structure can be used by main agents, sub-agents, and orchestrated worker
flows.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.execution_profile_trace import TRACE_EXECUTION_PROFILE_KEY

from ....models import Message, TurnTrace
from ....runtime_limits import (
    DEFAULT_TRACE_MAX_DICT_ITEMS,
    DEFAULT_TRACE_MAX_LIST_ITEMS,
    DEFAULT_TRACE_MAX_STRING,
)
from ....services.agent_definition_execution_outcomes import payload_resolution_metadata
from ....services.answer_evidence.record import ANSWER_EVIDENCE_KEY, read_answer_evidence
from ....services.decisions.gates import record_gate_outcome
from ....services.observability.run_capture import capture_mode, captured, remember_capture_mode
from ....services.observability.run_summary import agent_label, in_app_run_key, run_summary_fields, summary_row
from ....services.request_context import get_current_request_id, get_request_started_at
from ....time_utils import utc_now
from ..guards.response_guards import get_step_allowed_tools, get_step_field
from .turn_execution_binding import stamp_turn_execution_snapshot


def _trace_limits(trace_limits: dict[str, Any] | None) -> tuple[int, int, int]:
    limits = trace_limits or {}
    return (
        int(limits.get("trace_max_string") or DEFAULT_TRACE_MAX_STRING),
        int(limits.get("trace_max_list_items") or DEFAULT_TRACE_MAX_LIST_ITEMS),
        int(limits.get("trace_max_dict_items") or DEFAULT_TRACE_MAX_DICT_ITEMS),
    )


def compact_trace_value(value: Any, *, depth: int = 0, trace_limits: dict[str, Any] | None = None) -> Any:
    max_string, max_list_items, max_dict_items = _trace_limits(trace_limits)
    if depth > 6:
        return "[truncated]"
    if isinstance(value, str):
        if len(value) <= max_string:
            return value
        return value[:max_string] + "\n...[truncated]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        items = value[:max_list_items]
        compacted = [compact_trace_value(item, depth=depth + 1, trace_limits=trace_limits) for item in items]
        if len(value) > max_list_items:
            compacted.append(f"...[{len(value) - max_list_items} more items truncated]")
        return compacted
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_dict_items:
                compacted["__truncated__"] = f"{len(value) - max_dict_items} more keys truncated"
                break
            compacted[str(key)] = compact_trace_value(item, depth=depth + 1, trace_limits=trace_limits)
        return compacted
    return str(value)


def serialize_history_message_for_trace(
    message: Message, *, trace_limits: dict[str, Any] | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": message.id,
        "role": message.role,
        "content": compact_trace_value(message.content or "", trace_limits=trace_limits),
    }
    if message.tool_calls:
        entry["tool_calls"] = compact_trace_value(message.tool_calls, trace_limits=trace_limits)
    if message.tool_results:
        entry["tool_results"] = compact_trace_value(message.tool_results, trace_limits=trace_limits)
    if message.model:
        entry["model"] = message.model
    return entry


def _current_step_entry(current_step: dict | None, current_step_index: int) -> dict[str, Any] | None:
    if not current_step:
        return None
    return {
        "index": current_step_index,
        "name": str(current_step.get("name") or ""),
        "step_type": str(get_step_field(current_step, "stepType", "step_type", "") or ""),
        "instructions": str(current_step.get("instructions") or ""),
        "success_criteria": str(get_step_field(current_step, "successCriteria", "success_criteria", "") or ""),
        "allowed_tools": list(get_step_allowed_tools(current_step)),
        "tdd_cycle_phase": str(current_step.get("tddCyclePhase") or ""),
        "tdd_cycle_phase_title": str(current_step.get("tddCyclePhaseTitle") or ""),
        "tdd_cycle_phase_index": int(current_step.get("tddCyclePhaseIndex") or 0),
        "tdd_cycle_phase_total": int(current_step.get("tddCyclePhaseTotal") or 0),
    }


def build_turn_context_snapshot(
    *,
    system_prompt: str,
    personality_prompt: str,
    memory_prompt: str,
    skills_prompt: str,
    summary_context_messages: list[dict[str, Any]],
    history: list[Message],
    thinking_level: str | None,
    runtime_target_id: str | None,
    system_context: dict[str, Any] | None,
    agent_definition: dict | None,
    current_step: dict | None,
    current_step_index: int,
    context_plan: dict[str, Any] | None = None,
    request_analysis: dict[str, Any] | None = None,
    prompt_config: dict[str, Any] | None = None,
    request_id: str | None = None,
    trace_limits: dict[str, Any] | None = None,
    execution_profile_trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = compact_trace_value(
        {
            "request_id": request_id or "",
            "system_prompt": system_prompt,
            "personality_prompt": personality_prompt,
            "memory_prompt": memory_prompt,
            "skills_prompt": skills_prompt,
            "summary_context_messages": summary_context_messages,
            "recent_history": [serialize_history_message_for_trace(msg, trace_limits=trace_limits) for msg in history],
            "thinking_level": thinking_level or "",
            "runtime_target_id": runtime_target_id or "",
            "system_context": system_context or {},
            "agent": {
                "name": str((agent_definition or {}).get("name") or ""),
                "type": str((agent_definition or {}).get("agentType") or ""),
                "execution_mode": str((agent_definition or {}).get("executionMode") or ""),
                # Which agent-definition source produced these instructions —
                # the published revision, or the named draft row. Persisted on the
                # trace so a reviewer never has to assume it.
                **payload_resolution_metadata(agent_definition),
            },
            "context_plan": context_plan or {},
            "prompt_config": prompt_config or {},
            "request_analysis": request_analysis or {},
            "current_step": _current_step_entry(current_step, current_step_index),
        },
        trace_limits=trace_limits,
    )
    snapshot.update(_frozen_profile_entry(execution_profile_trace))
    return snapshot


def _frozen_profile_entry(execution_profile_trace: Any) -> dict[str, Any]:
    if not isinstance(execution_profile_trace, Mapping) or not execution_profile_trace:
        return {}
    # Independent copy per trace: the run's frozen projection is never shared or mutated.
    return {TRACE_EXECUTION_PROFILE_KEY: copy.deepcopy(dict(execution_profile_trace))}


def gate_trace_context_snapshot(tool_context: Any) -> dict[str, Any]:
    """Context snapshot for gate outcomes persisted before the loop runs.

    Carries only the run's frozen execution profile projection (set at run
    preparation), so a blocked turn's trace names the profile it was blocked under.
    """
    return _frozen_profile_entry(getattr(tool_context, "execution_profile_trace", None))


def _pop_frozen_entries(enriched_context_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Take the entries that bypass compaction out of the snapshot; they are re-applied after it.

    The caller passes the run's frozen profile projection inside the snapshot; the
    session row is never re-read here (a later turn may have rewritten it). The
    projection is already bounded and redacted, so it skips compaction and can
    never be truncated away by the dict-item limit.
    """
    frozen_profile = _frozen_profile_entry(enriched_context_snapshot.pop(TRACE_EXECUTION_PROFILE_KEY, None))
    # The answer evidence decision is closed and bounded too, and is kept the same way.
    answer_evidence = read_answer_evidence(enriched_context_snapshot)
    enriched_context_snapshot.pop(ANSWER_EVIDENCE_KEY, None)
    if answer_evidence is not None:
        frozen_profile[ANSWER_EVIDENCE_KEY] = answer_evidence
    return frozen_profile


async def _record_run_summary(
    db: AsyncSession,
    trace: TurnTrace,
    *,
    request_id: str,
    raw_output: Any,
    usage: Any,
    context_snapshot: dict[str, Any],
) -> None:
    run_key = in_app_run_key(request_id, trace.id)
    # Runs (observability) reads the summary row; the trace payload is never aggregated.
    db.add(summary_row(trace, run_summary_fields(
        run_key=run_key, raw_output=raw_output, usage=usage,
        started_at=get_request_started_at(request_id), label=agent_label(context_snapshot),
    )))
    # A gate that stopped the turn left its marker in the output: that is the run's decision record.
    await record_gate_outcome(db, session_id=trace.session_id, run_key=run_key, raw_output=raw_output)


async def persist_turn_trace(
    *,
    db: AsyncSession,
    session_id: str,
    message_id: str | None,
    provider: str | None,
    model: str | None,
    input_messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    tool_trace: list[dict[str, Any]] | None,
    raw_output: dict[str, Any],
    usage: dict[str, Any] | None,
    trace_limits: dict[str, Any] | None = None,
) -> TurnTrace:
    enriched_context_snapshot = dict(context_snapshot or {})
    frozen_profile = _pop_frozen_entries(enriched_context_snapshot)
    if not enriched_context_snapshot.get("request_id"):
        enriched_context_snapshot["request_id"] = get_current_request_id() or ""
    compact_input_messages = compact_trace_value(input_messages, trace_limits=trace_limits)
    # The bounded execution snapshot is stamped after compaction so trace limits
    # can never truncate it away.
    compact_context_snapshot = stamp_turn_execution_snapshot(
        session_id,
        compact_trace_value(enriched_context_snapshot, trace_limits=trace_limits),
    )
    # The run's frozen execution-profile projection is re-applied for the same reason.
    # Both writers own disjoint reserved keys; neither may drop the other.
    compact_context_snapshot.update(frozen_profile)
    compact_tool_trace = compact_trace_value(tool_trace or [], trace_limits=trace_limits)
    compact_raw_output = compact_trace_value(raw_output, trace_limits=trace_limits)
    compact_usage = compact_trace_value(usage or {}, trace_limits=trace_limits)
    trace_id = str(uuid.uuid4())
    request_id = str(compact_context_snapshot.get("request_id") or "")
    # The Workspace capture policy applies at storage; secrets are redacted in every mode.
    mode = await capture_mode(db, session_id)
    stored_input, stored_context, stored_tools, stored_output = captured(
        mode, input_messages=compact_input_messages,
        context_snapshot=compact_context_snapshot, tool_trace=compact_tool_trace, raw_output=compact_raw_output,
    )
    trace = TurnTrace(
        id=trace_id,
        session_id=session_id,
        message_id=message_id,
        provider=provider or "",
        model=model or "",
        input_messages_json=stored_input,
        context_snapshot_json=stored_context,
        tool_trace_json=stored_tools,
        raw_output=stored_output,
        usage_json=compact_usage,
        created_at=utc_now(),
    )
    remember_capture_mode(trace, mode)
    db.add(trace)
    await _record_run_summary(
        db, trace, request_id=request_id, raw_output=compact_raw_output, usage=compact_usage,
        context_snapshot=compact_context_snapshot,
    )
    return trace
