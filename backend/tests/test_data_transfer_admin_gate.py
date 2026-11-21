"""Backup & restore is gated by the platform-admin role, not by the account name."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Project, Role, User, UserRole
from app.services.auth import hash_password
from app.services.data_transfer import create_data_export_job, create_data_import_job


async def _user_with_role(db, role_name: str) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=f"ops-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_project_backup_export_works_for_any_platform_admin(db):
    second_admin = await _user_with_role(db, "admin")
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    job = await create_data_export_job(
        db,
        current_user=second_admin,
        export_type="project_backup",
        scope_type="project",
        scope_id=project.id,
        format_name="json",
    )

    assert job["status"] == "completed"


@pytest.mark.asyncio
async def test_backup_and_restore_refuse_a_non_admin(db):
    viewer = await _user_with_role(db, "viewer")
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    with pytest.raises(HTTPException) as export_error:
        await create_data_export_job(
            db,
            current_user=viewer,
            export_type="project_backup",
            scope_type="project",
            scope_id=project.id,
            format_name="json",
        )
    with pytest.raises(HTTPException) as import_error:
        await create_data_import_job(
            db,
            current_user=viewer,
            import_type="admin_config_backup",
            source_format="json",
            payload_json={},
            payload_text=None,
            target_project_id=None,
        )

    assert export_error.value.status_code == 403
    assert import_error.value.status_code == 403
