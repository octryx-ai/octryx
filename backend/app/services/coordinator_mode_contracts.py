"""Coordinator state contracts per coordinator mode: direct, sub-agent group and worker delegation."""

from __future__ import annotations

from typing import Any

from ..models import Session, SubAgentGroup, WorkerDelegation
from ..schemas.operations.coordinator import CoordinatorMode, CoordinatorStateContract
from .session.run_state import get_session_run_completion_reason, get_session_run_status
from .sub_agent_group.telemetry import summarize_sub_agent_group_telemetry

_TERMINAL_DELEGATION_STATUSES = frozenset({"completed", "failed", "declined"})
_ACTIVE_DELEGATION_STATUSES = frozenset({"pending", "accepted", "in_progress"})


def _normalize_ids(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _session_run_status(session: Session) -> str:
    explicit = get_session_run_status(session)
    if explicit:
        return explicit
    status = str(session.status or "").strip().lower()
    if status == "running":
        return "in_progress"
    if status == "pending_approval":
        return "awaiting_approval"
    if status == "awaiting_subagents":
        return "awaiting_subagents"
    if status == "completed":
        return "completed"
    if status == "error":
        return "failed"
    if status == "stopped":
        return "stopped"
    return ""


def _session_run_completion_reason(session: Session) -> str | None:
    reason = get_session_run_completion_reason(session)
    return reason or None


def _direct_contract(root_session: Session, child_session_ids: list[str]) -> CoordinatorStateContract:
    session_status = str(root_session.status or "").strip().lower() or "unknown"
    run_status = _session_run_status(root_session)
    active_run = session_status in {"running", "pending_approval", "awaiting_subagents"} or run_status in {
        "in_progress",
        "awaiting_approval",
        "awaiting_subagents",
    }
    aggregate_status = session_status if session_status != "running" else "in_progress"
    return CoordinatorStateContract(
        root_session_id=root_session.id,
        coordinator_mode="direct",
        aggregate_status=aggregate_status,
        session_status=session_status,
        run_status=run_status,
        run_completion_reason=_session_run_completion_reason(root_session),
        child_session_ids=child_session_ids,
        synthesis_ready=True,
        can_continue=not active_run,
        can_stop=active_run,
    )


def _determine_metadata_mode(root_session: Session) -> CoordinatorMode:
    metadata = dict(root_session.metadata_ or {})
    if metadata.get("workflow_contract") or metadata.get("workflow_id"):
        return "deterministic_workflow"
    if metadata.get("current_sub_agent_group_id"):
        return "sub_agent_group"
    trigger = str(metadata.get("trigger") or "").strip().lower()
    if trigger == "worker_delegation":
        return "worker_delegation"
    return "unknown"


def _sub_agent_group_contract(
    root_session: Session,
    *,
    group: SubAgentGroup,
    child_session_ids: list[str],
) -> CoordinatorStateContract:
    telemetry = summarize_sub_agent_group_telemetry(group)
    progress = telemetry["progress"]
    readiness = telemetry["readiness"]
    terminal_state = str(telemetry["terminal_state"] or "").strip().lower() or "unknown"

    if progress["pending_children"] > 0:
        aggregate_status = "awaiting_children"
    elif readiness["parent_resume_ready"]:
        aggregate_status = "ready_to_continue"
    else:
        aggregate_status = terminal_state

    return CoordinatorStateContract(
        root_session_id=root_session.id,
        coordinator_mode="sub_agent_group",
        aggregate_status=aggregate_status,
        session_status=str(root_session.status or "").strip().lower() or "unknown",
        run_status=_session_run_status(root_session),
        run_completion_reason=_session_run_completion_reason(root_session),
        child_session_ids=_normalize_ids(list(group.child_session_ids_json or []) + child_session_ids),
        delegated_session_ids=[],
        sub_agent_group_id=group.id,
        delegation_ids=[],
        progress_counts={
            "total_children": int(progress["total_children"] or 0),
            "completed_children": int(progress["completed_children"] or 0),
            "failed_children": int(progress["failed_children"] or 0),
            "timed_out_children": int(progress["timed_out_children"] or 0),
            "terminal_children": int(progress["terminal_children"] or 0),
            "pending_children": int(progress["pending_children"] or 0),
        },
        progress_ratio=float(progress["completion_ratio"] or 0.0),
        synthesis_ready=bool(readiness["parent_resume_ready"]),
        can_continue=bool(readiness["parent_resume_ready"]),
        can_stop=not bool(readiness["group_is_terminal"]),
    )


def _normalize_delegation_status(status: str | None) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in _TERMINAL_DELEGATION_STATUSES or normalized in _ACTIVE_DELEGATION_STATUSES:
        return normalized
    return "unknown"


def _worker_delegation_contract(
    root_session: Session,
    *,
    delegations: list[WorkerDelegation],
    child_session_ids: list[str],
) -> CoordinatorStateContract:
    delegation_ids = _normalize_ids([row.id for row in delegations])
    delegated_session_ids = _normalize_ids([row.delegated_session_id for row in delegations])
    statuses = [_normalize_delegation_status(row.status) for row in delegations]
    all_terminal = bool(statuses) and all(status in _TERMINAL_DELEGATION_STATUSES for status in statuses)

    if any(status in {"accepted", "in_progress"} for status in statuses):
        aggregate_status = "delegation_in_progress"
    elif any(status == "pending" for status in statuses):
        aggregate_status = "awaiting_delegation_response"
    elif all_terminal and any(status == "failed" for status in statuses):
        aggregate_status = "completed_with_failures"
    elif all_terminal:
        aggregate_status = "ready_to_continue"
    else:
        aggregate_status = "unknown"

    return CoordinatorStateContract(
        root_session_id=root_session.id,
        coordinator_mode="worker_delegation",
        aggregate_status=aggregate_status,
        session_status=str(root_session.status or "").strip().lower() or "unknown",
        run_status=_session_run_status(root_session),
        run_completion_reason=_session_run_completion_reason(root_session),
        child_session_ids=_normalize_ids(child_session_ids + delegated_session_ids),
        delegated_session_ids=delegated_session_ids,
        sub_agent_group_id=None,
        delegation_ids=delegation_ids,
        progress_counts={
            "total_children": len(delegation_ids),
            "completed_children": sum(1 for status in statuses if status == "completed"),
            "failed_children": sum(1 for status in statuses if status == "failed"),
            "timed_out_children": 0,
            "terminal_children": sum(1 for status in statuses if status in _TERMINAL_DELEGATION_STATUSES),
            "pending_children": sum(1 for status in statuses if status not in _TERMINAL_DELEGATION_STATUSES),
        },
        progress_ratio=(sum(1 for status in statuses if status in _TERMINAL_DELEGATION_STATUSES) / len(statuses))
        if statuses
        else None,
        synthesis_ready=all_terminal,
        can_continue=all_terminal,
        can_stop=not all_terminal,
    )
