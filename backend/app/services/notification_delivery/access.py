from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import NotificationPreference, Role, User, UserRole
from ..admin.governance.admin_access_service import is_global_admin


def channel_plugin_id(channel_type: str) -> str:
    normalized = str(channel_type or "").strip().lower()
    return {"email": "email", "slack": "slack", "teams": "msteams"}.get(normalized, normalized)


async def require_admin_user(db: AsyncSession, current_user: User) -> None:
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Admin access required")


async def user_role_names(db: AsyncSession, user_id: str) -> set[str]:
    rows = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return {row[0] for row in rows.all()}


async def notification_preferences(db: AsyncSession, user_id: str) -> NotificationPreference:
    pref = await db.get(NotificationPreference, user_id)
    if pref is None:
        pref = NotificationPreference(user_id=user_id)
        db.add(pref)
        await db.flush()
    return pref
