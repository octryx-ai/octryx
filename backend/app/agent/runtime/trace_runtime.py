"""Generic turn trace runtime helpers."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime.turn_execution_binding import stamp_turn_execution_snapshot
from app.models import TurnTrace
from app.runtime_limits import (
    DEFAULT_TRACE_MAX_DICT_ITEMS,
    DEFAULT_TRACE_MAX_LIST_ITEMS,
    DEFAULT_TRACE_MAX_STRING,
)
from app.services.answer_evidence.record import ANSWER_EVIDENCE_KEY, read_answer_evidence
from app.services.decisions.gates import record_gate_outcome
from app.services.execution_profile_trace import TRACE_EXECUTION_PROFILE_KEY
from app.services.observability.run_capture import capture_mode, captured, remember_capture_mode
from app.services.observability.run_summary import agent_label, in_app_run_key, run_summary_fields, summary_row
from app.services.request_context import get_current_request_id, get_request_started_at
from app.time_utils import utc_now


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


def _frozen_profile_entry(execution_profile_trace: Any) -> dict[str, Any]:
    if not isinstance(execution_profile_trace, Mapping) or not execution_profile_trace:
        return {}
    # Independent copy per trace: the run's frozen projection is never shared or mutated.
    return {TRACE_EXECUTION_PROFILE_KEY: copy.deepcopy(dict(execution_profile_trace))}


def _pop_frozen_entries(enriched_context_snapshot: dict[str, Any]) -> dict[str, Any]:
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
