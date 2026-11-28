"""Owner-scoped, read-only loading of the per-turn evidence of ``turn_execution_summary.v1``."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, Session, ToolCall, TurnTrace
from ...models.runtime.artifact_store import ToolArtifact
from ..content_routing.notices import turn_content_obligations
from ..product_run.turn_outcome import admission_refusal_of_trace
from ..prompt_catalog import prompt_set_scope, resolve_prompt_set
from ..workflow_contracts.decisions import WORKFLOW_DECISION_REQUEST_KEY
from .artifact_visibility import load_user_turn_trace
from .turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY, read_turn_execution_snapshot
from .turn_execution_summary import (
    TurnApprovalEvidence,
    TurnArtifactEvidence,
    TurnExecutionEvidence,
    TurnToolCallEvidence,
    build_turn_execution_summary,
    runtime_outcome_from_trace,
)
from .turn_run_identity import resolve_stamped_turn_run

MAX_TURN_TRACES = 100
MAX_TURN_TOOL_CALLS = 200
_TURN_TOKEN_PATH = (TURN_EXECUTION_SNAPSHOT_KEY, "turn", "user_message_id")


def _timestamp(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _result_markers(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    if result.get("_artifact_storage"):
        preview = result.get("preview")
        compact = preview.get("compact_result") if isinstance(preview, dict) else None
        return compact if isinstance(compact, dict) else {}
    return result


def _pending_approval_id(result: dict[str, Any]) -> str | None:
    if not result.get("approval_required"):
        return None
    approval_id = result.get("approval_id")
    return str(approval_id) if isinstance(approval_id, str) and approval_id else None


def _is_clarification_pause(result: dict[str, Any]) -> bool:
    return result.get("status") == "paused" and bool(result.get("paused"))


def _decision_request(raw_output: Any) -> Any:
    return raw_output.get(WORKFLOW_DECISION_REQUEST_KEY) if isinstance(raw_output, dict) else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _usage_count(usage: Any, *keys: str) -> int | None:
    data = usage if isinstance(usage, dict) else {}
    for key in keys:
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _turn_usage(traces: list[TurnTrace]) -> dict[str, int | None]:
    totals: dict[str, int | None] = {"prompt_tokens": None, "completion_tokens": None}
    for row in traces:
        for total_key, keys in (
            ("prompt_tokens", ("prompt_tokens", "input_tokens")),
            ("completion_tokens", ("completion_tokens", "output_tokens")),
        ):
            count = _usage_count(row.usage_json, *keys)
            if count is not None:
                totals[total_key] = (totals[total_key] or 0) + count
    return totals


def _tool_trace_calls(tool_trace: Any) -> tuple[TurnToolCallEvidence, ...]:
    entries = tool_trace if isinstance(tool_trace, list) else []
    return tuple(
        TurnToolCallEvidence(name=entry.get("tool_name"), status=None)
        for entry in entries[:MAX_TURN_TOOL_CALLS]
        if isinstance(entry, dict)
    )


def _turn_token(trace: TurnTrace) -> str | None:
    _status, snapshot = read_turn_execution_snapshot(trace.context_snapshot_json)
    return snapshot["turn"]["user_message_id"] if snapshot is not None else None


def _turn_order(trace: TurnTrace) -> tuple[datetime, int]:
    _status, snapshot = read_turn_execution_snapshot(trace.context_snapshot_json)
    sequence = snapshot["turn"]["sequence"] if snapshot is not None else None
    created_at = trace.created_at if isinstance(trace.created_at, datetime) else datetime.min
    return created_at, sequence if sequence is not None else -1


async def _turn_traces(db: AsyncSession, trace: TurnTrace) -> list[TurnTrace]:
    token = _turn_token(trace)
    if token is None:
        return [trace]
    rows = (
        await db.execute(
            select(TurnTrace)
            .where(
                TurnTrace.session_id == trace.session_id,
                TurnTrace.context_snapshot_json[_TURN_TOKEN_PATH].as_string() == token,
            )
            .order_by(TurnTrace.created_at.desc(), TurnTrace.id.desc())
            .limit(MAX_TURN_TRACES)
        )
    ).scalars()
    members = {row.id: row for row in rows if row.session_id == trace.session_id and _turn_token(row) == token}
    members.setdefault(trace.id, trace)
    return sorted(members.values(), key=_turn_order)


async def load_turn_execution_evidence(db: AsyncSession, trace: TurnTrace) -> TurnExecutionEvidence:
    turn_traces = await _turn_traces(db, trace)
    final_trace = turn_traces[-1]
    intermediate = final_trace.id != trace.id
    # The final trace speaks for the whole turn; an intermediate one for its own step.
    evidence_traces = [trace] if intermediate else turn_traces
    message_ids = [row.message_id for row in evidence_traces if row.message_id]
    tool_rows: list[ToolCall] = []
    if message_ids:
        tool_rows = list(
            (
                await db.execute(
                    select(ToolCall)
                    .where(ToolCall.session_id == trace.session_id, ToolCall.message_id.in_(message_ids))
                    .order_by(ToolCall.created_at.asc())
                    .limit(MAX_TURN_TOOL_CALLS)
                )
            ).scalars()
        )

    approval_tools: dict[str, str] = {}
    clarification_requested = False
    for row in tool_rows:
        markers = _result_markers(row.result)
        approval_id = _pending_approval_id(markers)
        if approval_id is not None:
            approval_tools.setdefault(approval_id, str(row.tool_name or ""))
        clarification_requested = clarification_requested or _is_clarification_pause(markers)

    approval_rows: dict[str, Approval] = {}
    if approval_tools:
        approval_rows = {
            row.id: row
            for row in (
                await db.execute(
                    select(Approval).where(
                        Approval.id.in_(list(approval_tools)),
                        Approval.session_id == trace.session_id,
                    )
                )
            ).scalars()
        }
    approvals = tuple(
        TurnApprovalEvidence(
            approval_id=approval_id,
            tool_name=tool_name,
            # A marker without a same-session approval row is unresolvable, not approved.
            status=approval_rows[approval_id].status if approval_id in approval_rows else None,
            created_at=_timestamp(approval_rows[approval_id].created_at) if approval_id in approval_rows else None,
            resolved_at=_timestamp(approval_rows[approval_id].resolved_at) if approval_id in approval_rows else None,
        )
        for approval_id, tool_name in approval_tools.items()
    )

    artifacts: tuple[TurnArtifactEvidence, ...] = ()
    if tool_rows:
        artifact_rows = (
            await db.execute(
                select(
                    ToolArtifact.id,
                    ToolArtifact.tool_name,
                    ToolArtifact.payload_size_bytes,
                    ToolArtifact.created_at,
                )
                .where(
                    ToolArtifact.id.in_([row.id for row in tool_rows]),
                    ToolArtifact.session_id == trace.session_id,
                )
                .order_by(ToolArtifact.created_at.asc())
            )
        ).all()
        artifacts = tuple(
            TurnArtifactEvidence(
                artifact_id=row.id,
                tool_name=row.tool_name,
                size_bytes=row.payload_size_bytes,
                created_at=_timestamp(row.created_at),
            )
            for row in artifact_rows
        )

    tool_calls = (
        tuple(TurnToolCallEvidence(name=row.tool_name, status=row.status) for row in tool_rows)
        if tool_rows
        else _tool_trace_calls([entry for row in evidence_traces for entry in _list(row.tool_trace_json)])
    )
    return TurnExecutionEvidence(
        trace_id=str(trace.id),
        session_id=str(trace.session_id),
        message_id=trace.message_id,
        provider=trace.provider,
        model=trace.model,
        context_snapshot=trace.context_snapshot_json,
        runtime_outcome=runtime_outcome_from_trace(trace.context_snapshot_json, trace.raw_output),
        admission_refusal=admission_refusal_of_trace(trace.provider, trace.raw_output),
        intermediate=intermediate,
        clarification_requested=clarification_requested,
        decision_request=None if intermediate else _decision_request(trace.raw_output),
        usage=_turn_usage(evidence_traces),
        tool_calls=tool_calls,
        approvals=approvals,
        artifacts=artifacts,
        # The final trace speaks for the whole turn, so a notice is shown once, on the turn's last message.
        content_obligations=() if intermediate else tuple(turn_content_obligations(
            [row.raw_output for row in evidence_traces],
            [(row.tool_name, _result_markers(row.result)) for row in tool_rows])),
    )


def _workflow_run_started(context_snapshot: Any, session_metadata: Any) -> bool:
    from ..workflow_routing.phased_start_run import started_run_of

    _status, snapshot = read_turn_execution_snapshot(context_snapshot)
    proposal = (snapshot or {}).get("workflow_proposal") or {}
    return bool(proposal.get("proposal_id")) and started_run_of(session_metadata, proposal["proposal_id"]) is not None


async def load_user_turn_execution_summary(
    db: AsyncSession,
    *,
    user_id: str,
    trace_id: str,
) -> dict[str, Any] | None:
    # Unknown and not owned answer alike.
    trace = await load_user_turn_trace(db, user_id=user_id, trace_id=trace_id)
    if trace is None:
        return None
    evidence = await load_turn_execution_evidence(db, trace)
    product_run = await resolve_stamped_turn_run(
        db, context_snapshot=trace.context_snapshot_json, session_id=trace.session_id, owner_user_id=user_id
    )
    # User-facing labels that are catalog data resolve at the session's Workspace scope (no turn is bound).
    workspace_id, session_metadata = (
        await db.execute(select(Session.project_id, Session.metadata_).where(Session.id == trace.session_id))
    ).one_or_none() or (None, None)
    prompt_set = await resolve_prompt_set(db, workspace_id=workspace_id)
    with prompt_set_scope(prompt_set):
        return build_turn_execution_summary(
            replace(
                evidence,
                product_run=product_run,
                workflow_run_started=_workflow_run_started(trace.context_snapshot_json, session_metadata),
            )
        )


__all__ = ["load_turn_execution_evidence", "load_user_turn_execution_summary"]
