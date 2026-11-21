"""LDAP sync helpers."""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy import select

from ...models import Personality, Role, User, UserRole
from ...services.auth import hash_password
from ..context import ToolContext
from .common import _string


async def _sync_local_users_from_ldap(
    context: ToolContext,
    users: list[dict[str, object]],
    *,
    role_names: list[str],
) -> dict[str, object]:
    if context.db is None:
        return {"error": "A database session is required for local user provisioning"}
    created = 0
    updated = 0
    role_result = await context.db.execute(select(Role).where(Role.name.in_(role_names)))
    roles = {role.name: role for role in role_result.scalars().all()}
    synced_users: list[dict[str, str]] = []
    for user_payload in users:
        username = _string(user_payload.get("username"))
        email = _string(user_payload.get("email")) or f"{username}@ldap.local"
        if not username:
            continue
        result = await context.db.execute(select(User).where((User.username == username) | (User.email == email)))
        local_user = result.scalars().first()
        if local_user is None:
            local_user = User(
                id=str(uuid.uuid4()),
                username=username,
                email=email,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                auth_source="ldap",
                display_name=_string(user_payload.get("display_name") or username),
                is_active=True,
            )
            context.db.add(local_user)
            await context.db.flush()
            context.db.add(Personality(user_id=local_user.id))
            created += 1
        else:
            local_user.email = email
            local_user.display_name = _string(user_payload.get("display_name") or local_user.display_name or username)
            local_user.auth_source = "ldap"
            local_user.is_active = True
            updated += 1
        for role_name in role_names:
            role = roles.get(role_name)
            if role is None:
                continue
            existing_role = await context.db.execute(
                select(UserRole).where(UserRole.user_id == local_user.id, UserRole.role_id == role.id)
            )
            if existing_role.scalar_one_or_none() is None:
                context.db.add(UserRole(user_id=local_user.id, role_id=role.id))
        synced_users.append(
            {
                "id": local_user.id,
                "username": local_user.username,
                "email": local_user.email,
                "display_name": local_user.display_name or local_user.username,
            }
        )
    await context.db.commit()
    return {"created_count": created, "updated_count": updated, "synced_users": synced_users}
