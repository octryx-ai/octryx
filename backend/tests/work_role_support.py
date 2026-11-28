"""Assign seed work roles in tests the way ``role:<key>`` deciders and handoff owners read them."""

from __future__ import annotations

from sqlalchemy import select

from app.models.runtime.work_role_model import WorkRole, WorkRoleAssignment
from app.services.work_role_model.seeds import ensure_seed_catalog


async def assign_seed_role(db, workspace_id: str, role_key: str, *, user_id: str | None = None,
                           group_id: str | None = None) -> WorkRoleAssignment:
    assert bool(user_id) != bool(group_id), "assign to exactly one person or group"
    await ensure_seed_catalog(db)
    role = (await db.execute(select(WorkRole).where(WorkRole.key == role_key, WorkRole.project_id.is_(None)))
            ).scalar_one()
    row = WorkRoleAssignment(project_id=workspace_id, role_id=role.id,
                             subject_kind="user" if user_id else "group", user_id=user_id, group_id=group_id,
                             subject_key=user_id or group_id)
    db.add(row)
    await db.flush()
    return row


async def set_seed_role_active(db, row: WorkRoleAssignment, active: bool) -> WorkRoleAssignment:
    row.is_active = active
    row.version += 1
    await db.flush()
    return row
