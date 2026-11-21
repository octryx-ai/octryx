"""Admin tools for user account management."""

from __future__ import annotations

import uuid
from typing import Any

from app.tools.context import ToolContext

from ._admin_common import _require_admin


class AdminListUsersTool:
    name = "admin_list_users"
    description = (
        "List all users on the platform with their roles and status. "
        "Admin only. Returns a formatted summary of all user accounts."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from sqlalchemy import select

        from ...models import Role, User, UserRole

        result = await context.db.execute(select(User).order_by(User.created_at))
        users = result.scalars().all()
        out = []
        for user in users:
            role_result = await context.db.execute(
                select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
            )
            roles = [row[0] for row in role_result.all()]
            out.append(
                {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "display_name": user.display_name or user.username,
                    "roles": roles,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                }
            )
        return {"users": out, "count": len(out)}


class AdminCreateUserTool:
    name = "admin_create_user"
    description = (
        "Create a new user account. "
        "Admin only. Assigns the specified roles (default: viewer). "
        "Password must be at least 8 characters."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        username = str(params.get("username") or "").strip()
        email = str(params.get("email") or "").strip()
        password = str(params.get("password") or "").strip()
        display_name = str(params.get("display_name") or "").strip()
        roles = list(params.get("roles") or ["viewer"])
        if not username:
            return {"error": "username is required"}
        if not email or "@" not in email:
            return {"error": "valid email is required"}
        if not password or len(password) < 8:
            return {"error": "password must be at least 8 characters"}

        from sqlalchemy import select

        from ...models import Personality, Role, User, UserRole
        from ...services.auth import hash_password

        existing = await context.db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            return {"error": f"Username '{username}' already exists"}
        existing_email = await context.db.execute(select(User).where(User.email == email))
        if existing_email.scalar_one_or_none():
            return {"error": f"Email '{email}' already registered"}

        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            password_hash=hash_password(password),
            display_name=display_name or username,
            is_active=True,
        )
        context.db.add(user)
        await context.db.flush()

        assigned_roles = []
        for role_name in roles:
            role_result = await context.db.execute(select(Role).where(Role.name == role_name))
            role = role_result.scalar_one_or_none()
            if not role:
                return {"error": f"Role '{role_name}' does not exist. Available: admin, operator, viewer"}
            context.db.add(UserRole(user_id=user.id, role_id=role.id))
            assigned_roles.append(role_name)

        context.db.add(Personality(user_id=user.id))
        await context.db.commit()
        return {
            "status": "created",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "display_name": user.display_name,
                "roles": assigned_roles,
                "is_active": True,
            },
        }


class AdminUpdateUserTool:
    name = "admin_update_user"
    description = (
        "Update an existing user: change email, display name, password, active status, or roles. "
        "Identify user by username or user_id. Admin only. "
        "Only provide fields you want to change."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        identifier = str(params.get("username") or params.get("user_id") or "").strip()
        if not identifier:
            return {"error": "username or user_id is required"}

        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select

        from ...models import Role, User, UserRole
        from ...services.auth import hash_password

        result = await context.db.execute(select(User).where((User.username == identifier) | (User.id == identifier)))
        user = result.scalar_one_or_none()
        if not user:
            return {"error": f"User '{identifier}' not found"}

        changes = []
        from ...services.admin.governance.admin_user_service import _notify_account_recovery  # noqa: PLC0415
        from ...services.auth.audit import record_auth_audit_event  # noqa: PLC0415

        if params.get("email") is not None:
            new_email = str(params["email"]).strip()
            user.email = new_email
            changes.append(f"email → {new_email}")
            # Like the panel, an email change by an admin is audited and the person is told.
            await _notify_account_recovery(context.db, user.id, "Your email address was changed by an administrator")
            record_auth_audit_event(context.db, user_id=str(context.user_id), action="admin.user.updated",
                                    resource_type="user", resource_id=user.id,
                                    details={"target_username": user.username, "changed": ["email"],
                                             "via": "agent_tool"})
        if params.get("display_name") is not None:
            user.display_name = str(params["display_name"]).strip()
            changes.append(f"display_name → {user.display_name}")
        if params.get("password") is not None:
            pw = str(params["password"])
            if len(pw) < 8:
                return {"error": "New password must be at least 8 characters"}
            user.password_hash = hash_password(pw)
            from ...services.devices.credential import revoke_user_device_grants  # noqa: PLC0415

            await revoke_user_device_grants(context.db, user_id=user.id)  # devices and paired phones end with it
            changes.append("password updated")
            await _notify_account_recovery(context.db, user.id, "Your password was reset by an administrator")
            record_auth_audit_event(context.db, user_id=str(context.user_id), action="admin.user.password_reset",
                                    resource_type="user", resource_id=user.id,
                                    details={"target_username": user.username, "via": "agent_tool"})
        if params.get("is_active") is not None:
            user.is_active = bool(params["is_active"])
            changes.append(f"is_active → {user.is_active}")
        if params.get("roles") is not None:
            new_roles = list(params["roles"])
            await context.db.execute(sa_delete(UserRole).where(UserRole.user_id == user.id))
            assigned = []
            for role_name in new_roles:
                role_result = await context.db.execute(select(Role).where(Role.name == role_name))
                role = role_result.scalar_one_or_none()
                if not role:
                    return {"error": f"Role '{role_name}' does not exist"}
                context.db.add(UserRole(user_id=user.id, role_id=role.id))
                assigned.append(role_name)
            changes.append(f"roles → {assigned}")

        if not changes:
            return {"message": "No changes provided", "user_id": user.id}

        await context.db.commit()
        await context.db.refresh(user)
        return {"status": "updated", "username": user.username, "changes": changes}


class AdminDeleteUserTool:
    name = "admin_delete_user"
    description = (
        "Deactivate or permanently delete a user. "
        "Admin only. Use action='deactivate' (default, reversible) or action='delete' (permanent). "
        "Cannot deactivate/delete yourself."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        identifier = str(params.get("username") or params.get("user_id") or "").strip()
        action = str(params.get("action") or "deactivate").lower()
        if not identifier:
            return {"error": "username or user_id is required"}

        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select

        from ...models import User, UserRole

        result = await context.db.execute(select(User).where((User.username == identifier) | (User.id == identifier)))
        user = result.scalar_one_or_none()
        if not user:
            return {"error": f"User '{identifier}' not found"}
        if user.id == context.user_id:
            return {"error": "You cannot deactivate or delete your own account"}

        if action == "delete":
            await context.db.execute(sa_delete(UserRole).where(UserRole.user_id == user.id))
            await context.db.delete(user)
            await context.db.commit()
            return {"status": "deleted", "username": identifier}

        user.is_active = False
        await context.db.commit()
        return {"status": "deactivated", "username": user.username}


__all__ = [
    "AdminCreateUserTool",
    "AdminDeleteUserTool",
    "AdminListUsersTool",
    "AdminUpdateUserTool",
]
