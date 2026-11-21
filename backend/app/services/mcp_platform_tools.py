"""Platform MCP tool implementations beyond the knowledge family.

Read-oriented first wave: tasks (list/runs), approvals (list, under the
visibility rule of ``services/approval/access``), effective policies (read).
Every tool declares its required OAuth scope; dispatch rejects tokens without
it. Write operations (task_trigger, approval_request) are handled separately
by the external-session bridge.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval, Task, TaskRun, User
from .approval.access import approval_visibility_clause
from .exec_policy import get_effective_exec_policy_config
from .project import get_user_project_ids
from .run_capability.schedule_capability import schedule_declared_capability
from .tool_access_policy_config import project_enforces_read_only_tools

MCP_PLATFORM_TOOL_SCOPES: dict[str, str] = {
    "task_list": "tasks:read",
    "task_runs": "tasks:read",
    "approval_list": "read",
    "policy_effective": "read",
}


def require_platform_tool_scope(tool_name: str, scopes: tuple[str, ...] | list[str]) -> None:
    required = MCP_PLATFORM_TOOL_SCOPES.get(tool_name)
    if required is None:
        raise HTTPException(status_code=404, detail=f"Unknown platform MCP tool: {tool_name}")
    if required not in set(scopes):
        raise HTTPException(
            status_code=403,
            detail=f"OAuth grant lacks required scope: {required}",
        )


async def _accessible_project_ids(
    db: AsyncSession,
    user: User,
    bound_project_ids: list[str] | None,
) -> set[str]:
    project_ids = set(await get_user_project_ids(user.id, db))
    if bound_project_ids:
        project_ids &= set(bound_project_ids)
    return project_ids


async def mcp_task_list(
    db: AsyncSession,
    *,
    user: User,
    bound_project_ids: list[str] | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    accessible = await _accessible_project_ids(db, user, bound_project_ids)
    query = select(Task).where(Task.owner_id == user.id)
    requested_project = str(arguments.get("project_id") or "").strip()
    if requested_project:
        if requested_project not in accessible:
            raise HTTPException(status_code=403, detail="Grant is not allowed to access this project")
        query = query.where(Task.project_id == requested_project)
    rows = (await db.execute(query.order_by(Task.created_at.desc()).limit(50))).scalars().all()
    items = [
        {
            "id": row.id,
            "project_id": row.project_id,
            "name": row.name,
            "description": row.description or "",
            "task_type": row.task_type,
            # No modes on the MCP surface: a task's capability is the class its config declares.
            "capability_class": schedule_declared_capability(row).capability_class,
            "schedule": row.schedule,
            "is_active": bool(row.is_active),
        }
        for row in rows
        if not row.project_id or row.project_id in accessible
    ]
    return {"items": items, "count": len(items)}


async def mcp_task_runs(
    db: AsyncSession,
    *,
    user: User,
    bound_project_ids: list[str] | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    task_id = str(arguments.get("task_id") or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    task = await db.get(Task, task_id)
    if task is None or task.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    accessible = await _accessible_project_ids(db, user, bound_project_ids)
    if task.project_id and task.project_id not in accessible:
        raise HTTPException(status_code=403, detail="Grant is not allowed to access this project")
    rows = (
        (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "id": row.id,
            "status": row.status,
            "session_id": row.session_id,
            "error": row.error,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }
        for row in rows
    ]
    return {"task_id": task_id, "items": items, "count": len(items)}


async def mcp_approval_list(
    db: AsyncSession,
    *,
    user: User,
    bound_project_ids: list[str] | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    status_filter = str(arguments.get("status") or "pending").strip().lower()
    if status_filter not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="status must be pending, approved or rejected")
    # The platform's one visibility rule for approvals (``services/approval/access``).
    query = select(Approval).where(Approval.status == status_filter)
    visible = await approval_visibility_clause(db, user.id)
    if visible is not None:
        query = query.where(visible)
    rows = (await db.execute(query.order_by(Approval.created_at.desc()).limit(50))).scalars().all()
    items = [
        {
            "id": row.id,
            "action": row.action,
            "status": row.status,
            "reason": row.reason,
            "session_id": row.session_id,
            "task_run_id": row.task_run_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }
        for row in rows
    ]
    return {"items": items, "count": len(items), "status": status_filter}


async def mcp_policy_effective(
    db: AsyncSession,
    *,
    user: User,
    bound_project_ids: list[str] | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    project_id = str(arguments.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    accessible = await _accessible_project_ids(db, user, bound_project_ids)
    if project_id not in accessible:
        raise HTTPException(status_code=403, detail="Grant is not allowed to access this project")
    config = await get_effective_exec_policy_config(db, project_id=project_id)
    from ..models import Project

    project = await db.get(Project, project_id)
    project_config = dict(project.config or {}) if project is not None and isinstance(project.config, dict) else {}
    return {
        "project_id": project_id,
        "read_only_tools_enforced": project_enforces_read_only_tools(project_config),
        "always_deny_patterns": list(config.get("always_deny_patterns") or []),
        "diagnosis_read_only_commands": list(config.get("diagnosis_read_only_commands") or []),
    }


MCP_PLATFORM_TOOL_HANDLERS = {
    "task_list": mcp_task_list,
    "task_runs": mcp_task_runs,
    "approval_list": mcp_approval_list,
    "policy_effective": mcp_policy_effective,
}


async def load_mcp_platform_tool(
    db: AsyncSession,
    *,
    user: User,
    bound_project_ids: list[str] | None,
    scopes: tuple[str, ...] | list[str],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    require_platform_tool_scope(tool_name, scopes)
    handler = MCP_PLATFORM_TOOL_HANDLERS[tool_name]
    return await handler(db, user=user, bound_project_ids=bound_project_ids, arguments=arguments)
