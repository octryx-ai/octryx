"""Session and message serialization helpers."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Session as AgentSession,
)
from ...models import (
    TaskRun,
)
from ...services.session.run_state import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_AWAITING_SUBAGENTS,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_IN_PROGRESS,
    RUN_STATUS_STOPPED,
    get_session_run_completion_reason,
    get_session_run_status,
    infer_completion_reason_from_content,
)
from ...services.session.turn_tasks import effective_session_status as _effective_session_status
from ...time_utils import ensure_utc, utc_isoformat

__all__ = [
    "_session_stop_reason",
    "_effective_session_run_status",
    "_effective_session_run_completion_reason",
    "_serialize_timestamp",
    "_sort_datetime_value",
    "_load_task_run_map",
    "_resolve_root_session",
    "_collect_session_tree",
    "_effective_session_status_for_chat",
    "_collect_session_tree_ids",
    "_sort_subthread_rows_recursively",
    "_propagate_terminal_status_to_descendants",
]


def _session_stop_reason(session: AgentSession) -> str | None:
    metadata = session.metadata_ or {}
    reason = metadata.get("last_stop_reason")
    return str(reason) if reason else None


def _effective_session_run_status(
    session: AgentSession,
    *,
    task_run: TaskRun | None = None,
    fallback_content: str | None = None,
) -> str:
    explicit_status = get_session_run_status(session)
    if explicit_status:
        return explicit_status

    session_status = _effective_session_status(session)
    if session_status == "running":
        return RUN_STATUS_IN_PROGRESS
    if session_status == "pending_approval":
        return RUN_STATUS_AWAITING_APPROVAL
    if session_status == "awaiting_subagents":
        return RUN_STATUS_AWAITING_SUBAGENTS
    if task_run and task_run.status:
        normalized_task_status = str(task_run.status).strip().lower()
        if normalized_task_status in {"queued", "pending", "running"}:
            return RUN_STATUS_IN_PROGRESS
        if normalized_task_status == "success":
            return RUN_STATUS_COMPLETED
        if normalized_task_status in {"cancelled", "canceled", "stopped"}:
            return RUN_STATUS_STOPPED
        if normalized_task_status in {"error", "failed"}:
            return RUN_STATUS_FAILED
    if _session_stop_reason(session) == "user_cancelled":
        return RUN_STATUS_STOPPED
    if session_status == "error":
        return RUN_STATUS_FAILED
    if session_status == "stopped":
        return RUN_STATUS_STOPPED
    if session_status == "completed":
        return RUN_STATUS_COMPLETED
    if fallback_content is not None:
        return RUN_STATUS_COMPLETED
    return ""


def _effective_session_run_completion_reason(
    session: AgentSession,
    *,
    task_run: TaskRun | None = None,
    fallback_content: str | None = None,
) -> str:
    explicit_reason = get_session_run_completion_reason(session)
    if explicit_reason:
        return explicit_reason

    run_status = _effective_session_run_status(session, task_run=task_run, fallback_content=fallback_content)
    if run_status == RUN_STATUS_AWAITING_APPROVAL:
        return "approval_required"
    if run_status == RUN_STATUS_AWAITING_SUBAGENTS:
        return "waiting_for_sub_agents"
    if run_status == RUN_STATUS_STOPPED and _session_stop_reason(session) == "user_cancelled":
        return "user_cancelled"
    if run_status == RUN_STATUS_FAILED:
        return "error"
    if fallback_content is not None:
        return infer_completion_reason_from_content(fallback_content)
    return ""


def _serialize_timestamp(value) -> str | None:
    return utc_isoformat(value)


def _sort_datetime_value(value) -> float:
    normalized = ensure_utc(value)
    if not normalized:
        return 0.0
    return normalized.timestamp()


async def _load_task_run_map(
    db: AsyncSession,
    sessions: list[AgentSession],
) -> tuple[dict[str, TaskRun], dict[str, TaskRun]]:
    session_ids = [session.id for session in sessions if session.id]
    task_run_ids = {
        str((session.metadata_ or {}).get("task_run_id") or "").strip()
        for session in sessions
        if (session.metadata_ or {}).get("task_run_id")
    }
    task_run_ids.discard("")
    if not task_run_ids and not session_ids:
        return {}, {}

    clauses = []
    if task_run_ids:
        clauses.append(TaskRun.id.in_(task_run_ids))
    if session_ids:
        clauses.append(TaskRun.session_id.in_(session_ids))

    task_runs = (
        (await db.execute(select(TaskRun).where(or_(*clauses)).order_by(TaskRun.started_at.desc()))).scalars().all()
    )

    task_run_by_id = {task_run.id: task_run for task_run in task_runs}
    latest_task_run_by_session_id: dict[str, TaskRun] = {}
    fallback_task_run_by_session_id: dict[str, TaskRun] = {}
    for task_run in task_runs:
        session_id = str(task_run.session_id or "").strip()
        if not session_id:
            continue
        fallback_task_run_by_session_id.setdefault(session_id, task_run)
        if session_id in latest_task_run_by_session_id:
            continue
        if (task_run.error or "").strip() == "Marked stale after scheduler startup":
            continue
        latest_task_run_by_session_id[session_id] = task_run
    for session_id, task_run in fallback_task_run_by_session_id.items():
        latest_task_run_by_session_id.setdefault(session_id, task_run)
    return task_run_by_id, latest_task_run_by_session_id


async def _resolve_root_session(db: AsyncSession, session: AgentSession | None) -> AgentSession | None:
    current = session
    while current and current.parent_session_id:
        parent = await db.get(AgentSession, current.parent_session_id)
        if not parent:
            break
        current = parent
    return current


async def _collect_session_tree(db: AsyncSession, root_session_id: str, *, user_id: str) -> list[AgentSession]:
    sessions = (
        (
            await db.execute(
                select(AgentSession).where(AgentSession.user_id == user_id).order_by(AgentSession.started_at.asc())
            )
        )
        .scalars()
        .all()
    )
    children_by_parent: dict[str, list[AgentSession]] = {}
    root_session: AgentSession | None = None
    for session in sessions:
        if session.id == root_session_id:
            root_session = session
        parent_id = str(session.parent_session_id or "").strip()
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(session)
    if not root_session:
        return []

    collected: list[AgentSession] = []
    stack = [root_session]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current.id in seen:
            continue
        seen.add(current.id)
        collected.append(current)
        for child in reversed(children_by_parent.get(current.id, [])):
            if child.id not in seen:
                stack.append(child)
    return collected


def _effective_session_status_for_chat(session: AgentSession, task_run: TaskRun | None = None) -> str:
    session_status = _effective_session_status(session)
    if session_status == "archived":
        return "archived"
    explicit_run_status = get_session_run_status(session)
    if explicit_run_status == RUN_STATUS_STOPPED or _session_stop_reason(session) == "user_cancelled":
        return "stopped"
    if task_run and task_run.status:
        if task_run.status == "success":
            return "completed"
        return task_run.status
    return session_status


def _collect_session_tree_ids(root_session_id: str, session_rows_by_id: dict[str, dict]) -> list[str]:
    collected: list[str] = []
    stack = [root_session_id]
    seen: set[str] = set()
    while stack:
        current_id = stack.pop()
        if current_id in seen or current_id not in session_rows_by_id:
            continue
        seen.add(current_id)
        collected.append(current_id)
        for child in session_rows_by_id[current_id].get("sub_threads") or []:
            child_id = str(child.get("id") or "").strip()
            if child_id and child_id not in seen:
                stack.append(child_id)
    return collected


def _sort_subthread_rows_recursively(rows: list[dict]) -> list[dict]:
    from ._serialization_ext import _thread_row_sort_key  # the sort key module imports this one

    sorted_rows = sorted(
        rows,
        key=_thread_row_sort_key,
        reverse=True,
    )
    for row in sorted_rows:
        row["sub_threads"] = _sort_subthread_rows_recursively(list(row.get("sub_threads") or []))
        row["sub_thread_count"] = len(row["sub_threads"])
    return sorted_rows


def _propagate_terminal_status_to_descendants(row: dict) -> None:
    parent_status = str(row.get("status") or "").strip().lower()
    if parent_status in {"error", "completed", "stopped"}:
        for child in row.get("sub_threads") or []:
            if str(child.get("status") or "").strip().lower() == "active":
                child["status"] = row["status"]
                if row.get("stop_reason") and not child.get("stop_reason"):
                    child["stop_reason"] = row["stop_reason"]
            _propagate_terminal_status_to_descendants(child)
        return
    for child in row.get("sub_threads") or []:
        _propagate_terminal_status_to_descendants(child)
