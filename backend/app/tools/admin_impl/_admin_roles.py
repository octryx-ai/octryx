"""Admin tools for role management."""

from __future__ import annotations

import uuid
from typing import Any

from app.tools.context import ToolContext

from ._admin_common import _require_admin


class AdminListRolesTool:
    name = "admin_list_roles"
    description = "List all roles on the platform with their descriptions and permissions. Admin only."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from sqlalchemy import func, select

        from ...models import Permission, Role, UserRole

        result = await context.db.execute(select(Role).order_by(Role.name))
        roles = result.scalars().all()
        out = []
        for role in roles:
            count_result = await context.db.execute(select(func.count()).where(UserRole.role_id == role.id))
            user_count = count_result.scalar() or 0
            perm_result = await context.db.execute(select(Permission).where(Permission.role_id == role.id))
            permissions = [{"resource": perm.resource, "action": perm.action} for perm in perm_result.scalars().all()]
            out.append(
                {
                    "id": role.id,
                    "name": role.name,
                    "description": role.description or "",
                    "user_count": user_count,
                    "permissions": permissions,
                }
            )
        return {"roles": out, "count": len(out)}


class AdminCreateRoleTool:
    name = "admin_create_role"
    description = (
        "Create a new custom role with optional permissions. "
        "Admin only. "
        "permissions is a list of {resource, action} objects. "
        "Available resources: users, sessions, agents, tasks, tools, knowledge, projects, webhooks, settings, memory, skills, audit. "
        "Available actions: read, write, delete."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        name = str(params.get("name") or "").strip().lower()
        description = str(params.get("description") or "")
        permissions = list(params.get("permissions") or [])
        if not name:
            return {"error": "name is required"}

        from sqlalchemy import select

        from ...models import Permission, Role

        existing = await context.db.execute(select(Role).where(Role.name == name))
        if existing.scalar_one_or_none():
            return {"error": f"Role '{name}' already exists"}

        role = Role(id=str(uuid.uuid4()), name=name, description=description)
        context.db.add(role)
        await context.db.flush()

        created_perms = []
        valid_resources = {
            "users",
            "sessions",
            "agents",
            "tasks",
            "tools",
            "knowledge",
            "projects",
            "webhooks",
            "settings",
            "memory",
            "skills",
            "audit",
        }
        valid_actions = {"read", "write", "delete"}
        for perm in permissions:
            resource = str(perm.get("resource", "")).lower()
            action = str(perm.get("action", "")).lower()
            if resource not in valid_resources:
                return {"error": f"Invalid resource '{resource}'. Valid: {sorted(valid_resources)}"}
            if action not in valid_actions:
                return {"error": f"Invalid action '{action}'. Valid: {sorted(valid_actions)}"}
            created = Permission(id=str(uuid.uuid4()), role_id=role.id, resource=resource, action=action)
            context.db.add(created)
            created_perms.append({"resource": resource, "action": action})

        await context.db.commit()
        return {
            "status": "created",
            "role": {"id": role.id, "name": name, "description": description, "permissions": created_perms},
        }


class AdminAssignRoleTool:
    name = "admin_assign_role"
    description = "Assign or remove a role from a user. Admin only. action='assign' or 'remove'."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        username = str(params.get("username") or "").strip()
        role_name = str(params.get("role") or "").strip()
        action = str(params.get("action") or "assign").lower()
        if not username or not role_name:
            return {"error": "username and role are required"}

        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select

        from ...models import Role, User, UserRole

        user_result = await context.db.execute(select(User).where((User.username == username) | (User.id == username)))
        user = user_result.scalar_one_or_none()
        if not user:
            return {"error": f"User '{username}' not found"}

        role_result = await context.db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if not role:
            return {"error": f"Role '{role_name}' not found"}

        if action == "remove":
            await context.db.execute(
                sa_delete(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
            )
            await context.db.commit()
            return {"status": "removed", "username": user.username, "role": role_name}

        existing = await context.db.execute(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
        )
        if existing.scalar_one_or_none():
            return {"message": f"User '{username}' already has role '{role_name}'"}
        context.db.add(UserRole(user_id=user.id, role_id=role.id))
        await context.db.commit()
        return {"status": "assigned", "username": user.username, "role": role_name}


__all__ = [
    "AdminAssignRoleTool",
    "AdminCreateRoleTool",
    "AdminListRolesTool",
]
