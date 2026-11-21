"""Dependency and session helpers for the task scheduler."""

from __future__ import annotations

from typing import Any


def build_task_session_title(task_name: str, task_run_id: str) -> str:
    return f"{task_name.strip() or 'Task'} · Run · {task_run_id[:8]}"


def build_task_session_metadata(task, task_run_id: str, *, trigger: str) -> dict[str, Any]:
    return {
        "title": build_task_session_title(task.name, task_run_id),
        "task_id": task.id,
        "task_name": task.name,
        "task_run_id": task_run_id,
        "task_type": task.task_type,
        "trigger": trigger,
    }


def detect_agent_failure(result_payload: dict | None) -> str | None:
    if not isinstance(result_payload, dict):
        return "missing_result_payload"
    explicit_error = str(result_payload.get("error") or "").strip()
    if explicit_error:
        return explicit_error
    response = str(result_payload.get("response") or "").strip()
    if response.startswith("Agent error:"):
        return response
    if "[Agent reached maximum tool call iterations]" in response:
        return "Agent reached maximum tool call iterations without completing the task"
    return None


async def evaluate_task_dependencies(db, task_id: str) -> dict[str, Any]:
    from sqlalchemy import select

    from ...models import Task, TaskDependency, TaskRun

    dependencies = (await db.execute(select(TaskDependency).where(TaskDependency.task_id == task_id))).scalars().all()
    if not dependencies:
        return {"ready": True, "unmet": []}

    task_ids = {dep.depends_on_task_id for dep in dependencies}
    tasks = (await db.execute(select(Task).where(Task.id.in_(task_ids)))).scalars().all()
    task_lookup = {task.id: task for task in tasks}
    terminal_statuses = {"success", "error", "failed", "cancelled", "skipped"}
    unmet: list[dict[str, Any]] = []
    for dep in dependencies:
        latest_run = (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.task_id == dep.depends_on_task_id)
                .order_by(TaskRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        latest_status = latest_run.status if latest_run else None
        condition = str(dep.condition or "success")
        satisfied = False
        if condition == "success":
            satisfied = latest_status == "success"
        elif condition == "failure":
            satisfied = latest_status in {"error", "failed", "cancelled"}
        elif condition == "always":
            satisfied = latest_status in terminal_statuses
        if not satisfied:
            unmet.append(
                {
                    "dependency_id": dep.id,
                    "depends_on_task_id": dep.depends_on_task_id,
                    "depends_on_task_name": task_lookup.get(dep.depends_on_task_id).name
                    if task_lookup.get(dep.depends_on_task_id)
                    else dep.depends_on_task_id,
                    "condition": condition,
                    "latest_status": latest_status,
                }
            )
    return {"ready": len(unmet) == 0, "unmet": unmet}


async def find_reusable_task_session(db, task):
    from sqlalchemy import select

    from ...models import Session

    query = select(Session).where(Session.user_id == task.owner_id, Session.status != "archived")
    if task.project_id:
        query = query.where(Session.project_id == task.project_id)
    else:
        query = query.where(Session.project_id.is_(None))
    result = await db.execute(query.order_by(Session.started_at.desc()))
    candidates = result.scalars().all()
    for session in candidates:
        metadata = dict(session.metadata_ or {})
        if str(metadata.get("task_id") or "").strip() != task.id:
            continue
        return session
    return None


async def collect_session_tree(db, root_session_id: str):
    from sqlalchemy import select

    from ...models import Session

    sessions: list[Session] = []
    frontier = [root_session_id]
    seen: set[str] = set()
    while frontier:
        current_ids = [session_id for session_id in frontier if session_id not in seen]
        frontier = []
        if not current_ids:
            continue
        seen.update(current_ids)
        result = await db.execute(
            select(Session).where((Session.id.in_(current_ids)) | (Session.parent_session_id.in_(current_ids)))
        )
        current_sessions = result.scalars().all()
        sessions.extend([session for session in current_sessions if session.id not in {item.id for item in sessions}])
        for session in current_sessions:
            if session.parent_session_id in current_ids and session.id not in seen:
                frontier.append(session.id)
    return sessions
