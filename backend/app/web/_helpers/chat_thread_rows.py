"""Sidebar thread rows: one row per chat session with its preview, status, approvals and stop facts."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.session.turn_tasks import effective_session_status as _effective_session_status

from ...models import Approval, Project, TurnTrace
from ...models import Session as AgentSession
from ...services.session.turn_execution_snapshot import RUNTIME_STOP_REASON_KEY, read_turn_execution_snapshot
from ...services.session.turn_execution_summary import runtime_outcome_from_trace
from ._serialization_ext import _session_is_pinned
from .chat_thread_row_facts import load_device_targets, session_last_activity
from .serialization import (
    _effective_session_run_completion_reason,
    _effective_session_run_status,
    _effective_session_status_for_chat,
    _load_task_run_map,
    _session_stop_reason,
    _sort_datetime_value,
)
from .session_preview_maps import _load_session_preview_maps
from .session_titles import _session_preview_from_content, _session_title_from_content


@dataclass(slots=True)
class ChatThreadRowsPayload:
    rows: list[dict[str, Any]]
    selected_row: dict[str, Any] | None
    task_run_map: dict[str, Any]
    latest_task_run_by_session_id: dict[str, Any]


@dataclass(slots=True)
class _ThreadRowFacts:
    task_run_map: dict[str, Any]
    latest_task_run_by_session_id: dict[str, Any]
    message_count_by_session_id: dict[str, int]
    first_user_content_by_session_id: dict[str, str]
    last_message_content_by_session_id: dict[str, str]
    last_assistant_content_by_session_id: dict[str, str]
    latest_turn_stopped: dict[str, str | None]
    device_targets: dict[str, Any]
    project_by_id: dict[str, Project]
    approval_counts_by_session_id: dict[str, dict[str, int]]


async def _load_latest_turn_stopped(db: AsyncSession, session_ids: list[str]) -> dict[str, str | None]:
    if not session_ids:
        return {}
    ranked = (
        select(
            TurnTrace.session_id,
            TurnTrace.context_snapshot_json,
            TurnTrace.raw_output,
            func.row_number()
            .over(partition_by=TurnTrace.session_id, order_by=(TurnTrace.created_at.desc(), TurnTrace.id.desc()))
            .label("rank"),
        )
        .where(TurnTrace.session_id.in_(session_ids))
        .subquery()
    )
    rows = (
        await db.execute(
            select(ranked.c.session_id, ranked.c.context_snapshot_json, ranked.c.raw_output).where(ranked.c.rank == 1)
        )
    ).all()
    return {
        str(row.session_id): _closed_stop_reason(row.context_snapshot_json)
        for row in rows
        if runtime_outcome_from_trace(row.context_snapshot_json, row.raw_output) == "stopped"
    }


def _closed_stop_reason(context_snapshot: Any) -> str | None:
    _status, snapshot = read_turn_execution_snapshot(context_snapshot)
    return snapshot[RUNTIME_STOP_REASON_KEY] if snapshot is not None else None


async def _load_project_map(db: AsyncSession, sessions: list[AgentSession]) -> dict[str, Project]:
    project_ids = sorted({session.project_id for session in sessions if session.project_id})
    project_by_id: dict[str, Project] = {}
    if project_ids:
        project_rows = (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()
        project_by_id = {project.id: project for project in project_rows}
    return project_by_id


async def _load_approval_counts(
    db: AsyncSession,
    sessions: list[AgentSession],
    session_ids: list[str],
) -> dict[str, dict[str, int]]:
    approval_counts_by_session_id: dict[str, dict[str, int]] = {}
    if sessions:
        approval_rows = (
            await db.execute(
                select(Approval.session_id, Approval.status, func.count(Approval.id))
                .where(Approval.session_id.in_(session_ids))
                .group_by(Approval.session_id, Approval.status)
            )
        ).all()
        for session_id, status, count in approval_rows:
            bucket = approval_counts_by_session_id.setdefault(str(session_id), {"total": 0, "pending": 0})
            count_value = int(count or 0)
            bucket["total"] += count_value
            if str(status or "").strip().lower() == "pending":
                bucket["pending"] += count_value
    return approval_counts_by_session_id


async def _load_thread_row_facts(db: AsyncSession, sessions: list[AgentSession]) -> _ThreadRowFacts:
    task_run_map, latest_task_run_by_session_id = await _load_task_run_map(db, sessions)
    session_ids = [session.id for session in sessions]
    (
        message_count_by_session_id,
        first_user_content_by_session_id,
        last_message_content_by_session_id,
        last_assistant_content_by_session_id,
    ) = await _load_session_preview_maps(db, session_ids)
    latest_turn_stopped = await _load_latest_turn_stopped(db, session_ids)
    device_targets = await load_device_targets(db, sessions)
    project_by_id = await _load_project_map(db, sessions)
    approval_counts_by_session_id = await _load_approval_counts(db, sessions, session_ids)
    return _ThreadRowFacts(
        task_run_map=task_run_map,
        latest_task_run_by_session_id=latest_task_run_by_session_id,
        message_count_by_session_id=message_count_by_session_id,
        first_user_content_by_session_id=first_user_content_by_session_id,
        last_message_content_by_session_id=last_message_content_by_session_id,
        last_assistant_content_by_session_id=last_assistant_content_by_session_id,
        latest_turn_stopped=latest_turn_stopped,
        device_targets=device_targets,
        project_by_id=project_by_id,
        approval_counts_by_session_id=approval_counts_by_session_id,
    )


def _thread_row(
    session: AgentSession,
    facts: _ThreadRowFacts,
    *,
    selected_session: AgentSession | None,
    automatic_runtime_label: str,
) -> dict[str, Any]:
    first_user_content = facts.first_user_content_by_session_id.get(session.id)
    last_message_content = facts.last_message_content_by_session_id.get(session.id)
    last_assistant_content = facts.last_assistant_content_by_session_id.get(session.id)
    project = facts.project_by_id.get(session.project_id) if session.project_id else None
    metadata = session.metadata_ or {}
    linked_task_run = facts.latest_task_run_by_session_id.get(session.id) or facts.task_run_map.get(
        str(metadata.get("task_run_id") or "").strip()
    )
    effective_status = _effective_session_status_for_chat(session, linked_task_run)
    row_title = _session_title_from_content(session, first_user_content)
    if linked_task_run and metadata.get("task_name"):
        ticket_ref = str(metadata.get("ticket_id") or "").strip() or linked_task_run.id
        row_title = f"{metadata.get('task_name')} · {ticket_ref} · Run · {linked_task_run.id[:8]}"
    approval_counts = facts.approval_counts_by_session_id.get(session.id, {})
    row = {
        "id": session.id,
        "title": row_title,
        "preview": _session_preview_from_content(last_message_content, limit=100),
        "message_count": facts.message_count_by_session_id.get(session.id, 0),
        "approval_count": approval_counts.get("total", 0),
        "pending_approval_count": approval_counts.get("pending", 0),
        "project_id": session.project_id or "",
        "project_name": project.name if project else "No project",
        "runtime_label": metadata.get("runtime_label") or automatic_runtime_label,
        "started_at": session.started_at,
        "last_activity_at": session_last_activity(session),
        "execution_target": facts.device_targets.get(session.id),
        "is_selected": bool(selected_session and selected_session.id == session.id),
        "status": _effective_session_status(session),
        "chat_status": effective_status,
        "run_status": _effective_session_run_status(
            session, task_run=linked_task_run, fallback_content=last_assistant_content
        ),
        "run_completion_reason": _effective_session_run_completion_reason(
            session, task_run=linked_task_run, fallback_content=last_assistant_content
        ),
        "stop_reason": _session_stop_reason(session),
        "latest_turn_stopped": session.id in facts.latest_turn_stopped,
        "latest_turn_stop_reason": facts.latest_turn_stopped.get(session.id),
        "is_pinned": _session_is_pinned(session),
        "parent_session_id": session.parent_session_id or "",
        "task_run_id": str(metadata.get("task_run_id") or "").strip(),
        "task_error": linked_task_run.error if linked_task_run else "",
        "sub_threads": [],
        "sub_thread_count": 0,
    }
    row["status"] = effective_status
    return row


async def build_chat_thread_rows(
    db: AsyncSession,
    *,
    sessions: list[AgentSession],
    selected_session: AgentSession | None,
    automatic_runtime_label: str,
) -> ChatThreadRowsPayload:
    facts = await _load_thread_row_facts(db, sessions)
    rows: list[dict[str, Any]] = []
    selected_row = None
    for session in sessions:
        row = _thread_row(
            session, facts, selected_session=selected_session, automatic_runtime_label=automatic_runtime_label
        )
        if selected_session and selected_session.id == session.id:
            selected_row = row
        rows.append(row)

    return ChatThreadRowsPayload(
        rows=sorted(rows, key=lambda session_row: _sort_datetime_value(session_row["last_activity_at"]), reverse=True),
        selected_row=selected_row,
        task_run_map=facts.task_run_map,
        latest_task_run_by_session_id=facts.latest_task_run_by_session_id,
    )
