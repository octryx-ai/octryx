"""Secret-safe audit of user and role changes, the self-edit and bootstrap admin guards and the seed repair."""

import pytest
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.bootstrap import seed_database
from app.models import AuditLog, Role, UserRole
from app.services.admin.governance.admin_role_service import create_role, delete_role, update_role
from app.services.admin.governance.admin_user_service import (
    create_user,
    deactivate_user,
    reset_user_password,
    update_user,
)


@pytest.mark.asyncio
async def test_admin_user_changes_record_secret_safe_audit(db, auth_user):
    user = await create_user(
        db,
        payload={
            "username": "audit_user",
            "email": "audit-user@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
        admin_id=auth_user.id,
    )

    await update_user(
        db,
        admin_id=auth_user.id,
        user_id=user["id"],
        payload={"display_name": "Audit User Updated", "roles": ["operator"]},
    )
    await reset_user_password(db, admin_id=auth_user.id, user_id=user["id"], password="new-password-123")

    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == "user", AuditLog.resource_id == user["id"])
            .order_by(AuditLog.created_at)
        )
    ).scalars().all()
    assert [row.action for row in rows] == [
        "admin.user.created",
        "admin.user.updated",
        "admin.user.password_reset",
    ]
    assert rows[1].details["changed_keys"] == ["display_name", "roles"]
    assert "password" not in rows[2].details


@pytest.mark.asyncio
async def test_admin_role_changes_record_audit(db, auth_user):
    role = await create_role(
        db,
        payload={"name": "audit-role", "description": "Audit role"},
        admin_id=auth_user.id,
    )

    await update_role(
        db,
        role_id=role["id"],
        payload={"description": "Audit role updated"},
        admin_id=auth_user.id,
    )
    await delete_role(db, role_id=role["id"], admin_id=auth_user.id)

    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == "role", AuditLog.resource_id == role["id"])
            .order_by(AuditLog.created_at)
        )
    ).scalars().all()
    assert [row.action for row in rows] == [
        "admin.role.created",
        "admin.role.updated",
        "admin.role.deleted",
    ]
    assert rows[1].details["changed_keys"] == ["description"]


@pytest.mark.asyncio
async def test_admin_user_service_prevents_self_edit(db):
    admin_user = await create_user(
        db,
        payload={
            "username": "self_admin",
            "email": "self-admin@example.com",
            "password": "password123",
            "roles": ["admin"],
        },
    )
    with pytest.raises(Exception) as error:
        await update_user(
            db,
            admin_id=admin_user["id"],
            user_id=admin_user["id"],
            payload={"is_active": False},
        )
    assert "cannot edit your own user" in str(error.value).lower()

    with pytest.raises(Exception) as password_error:
        await reset_user_password(
            db,
            admin_id=admin_user["id"],
            user_id=admin_user["id"],
            password="new-password-123",
        )
    assert "cannot reset your own password" in str(password_error.value).lower()


@pytest.mark.asyncio
async def test_admin_user_service_protects_bootstrap_admin(db, auth_user):
    with pytest.raises(Exception) as role_error:
        await update_user(
            db,
            admin_id="different-admin-id",
            user_id=auth_user.id,
            payload={"roles": ["viewer"]},
        )
    assert "bootstrap admin must keep the admin role" in str(role_error.value).lower()

    with pytest.raises(Exception) as active_error:
        await update_user(
            db,
            admin_id="different-admin-id",
            user_id=auth_user.id,
            payload={"is_active": False},
        )
    assert "bootstrap admin cannot be deactivated" in str(active_error.value).lower()

    with pytest.raises(Exception) as deactivate_error:
        await deactivate_user(db, admin_id="different-admin-id", user_id=auth_user.id)
    assert "bootstrap admin cannot be deactivated" in str(deactivate_error.value).lower()


@pytest.mark.asyncio
async def test_seed_database_repairs_bootstrap_admin_role(db, auth_user):
    viewer_role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one()

    auth_user.is_active = False
    auth_user.account_type = "technical"
    await db.execute(sa_delete(UserRole).where(UserRole.user_id == auth_user.id))
    db.add(UserRole(user_id=auth_user.id, role_id=viewer_role.id))
    await db.commit()

    await seed_database(db)
    await db.refresh(auth_user)

    role_names = (
        await db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == auth_user.id)
        )
    ).scalars().all()
    assert sorted(role_names) == ["admin"]
    assert auth_user.is_active is True
    assert auth_user.account_type == "human"
