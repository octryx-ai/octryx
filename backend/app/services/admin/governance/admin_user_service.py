"""Admin-panel service helpers for user management flows."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    APIKey,
    Personality,
    RefreshToken,
    User,
    UserRole,
)
from ....time_utils import utc_now
from ...auth import hash_password
from ...auth.audit import record_auth_audit_event
from ._admin_user_queries import _list_groups, _list_role_names, serialize_user
from ._admin_user_rules import (
    _is_bootstrap_admin_user,
    _normalize_account_type,
    _resolve_roles,
    _validate_bootstrap_admin_update,
)
from .admin_identity_group_service import replace_user_groups

logger = logging.getLogger(__name__)

async def _revoke_user_auth_material(db: AsyncSession, *, user_id: str) -> None:
    revoked_at = utc_now()
    refresh_tokens = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        )
    ).scalars().all()
    for token in refresh_tokens:
        token.revoked_at = revoked_at
        token.last_used_at = revoked_at

    api_keys = (
        await db.execute(select(APIKey).where(APIKey.user_id == user_id, APIKey.revoked_at.is_(None)))
    ).scalars().all()
    for api_key in api_keys:
        api_key.revoked_at = revoked_at
    from ...devices.credential import revoke_user_device_grants

    await revoke_user_device_grants(db, user_id=user_id)


def _user_audit_snapshot(user: User, roles: list[str]) -> dict[str, Any]:
    return {
        "username": user.username,
        "email": user.email or "",
        "account_type": user.account_type or "human",
        "roles": sorted(roles),
        "is_active": bool(user.is_active),
    }


async def create_user(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    admin_id: str | None = None,
) -> dict[str, Any]:
    username = str(payload.get("username") or "").strip()
    email = str(payload.get("email") or "").strip()
    password = str(payload.get("password") or "").strip()
    display_name = str(payload.get("display_name") or username).strip()
    account_type = _normalize_account_type(payload.get("account_type"))
    role_names = list(payload.get("roles") or (["technical"] if account_type == "technical" else ["viewer"]))
    if not username or not email or len(password) < 8:
        raise HTTPException(status_code=400, detail="username, email and password (min 8 chars) required")
    existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Username '{username}' already exists")
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        password_hash=hash_password(password),
        account_type=account_type,
        display_name=display_name,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    assigned: list[str] = []
    for role in await _resolve_roles(db, role_names):
        db.add(UserRole(user_id=user.id, role_id=role.id))
        assigned.append(role.name)
    db.add(Personality(user_id=user.id))
    await db.commit()
    record_auth_audit_event(
        db,
        user_id=admin_id,
        action="admin.user.created",
        resource_type="user",
        resource_id=user.id,
        details={"after": _user_audit_snapshot(user, assigned)},
    )
    if admin_id:
        await db.commit()
    return serialize_user(user, assigned)


async def update_user(db: AsyncSession, *, admin_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot edit your own user")
    _validate_bootstrap_admin_update(user, payload)
    before = _user_audit_snapshot(user, await _list_role_names(db, user.id))
    username = str(payload.get("username") or "").strip()
    email = str(payload.get("email") or "").strip()
    if username and username != user.username:
        existing = (
            await db.execute(
                select(User).where(User.id != user.id).where(or_(User.username == username, User.email == username))
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail=f"Username '{username}' already exists")
        user.username = username
    if email and email != user.email:
        existing = (
            await db.execute(
                select(User).where(User.id != user.id).where(or_(User.email == email, User.username == email))
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail=f"Email '{email}' already exists")
        user.email = email
        await _notify_account_recovery(db, user.id, "Your email address was changed by an administrator")
    if payload.get("is_active") is not None:
        user.is_active = bool(payload["is_active"])
        if not user.is_active:
            await _revoke_user_auth_material(db, user_id=user.id)
    if payload.get("display_name") is not None:
        display_name = str(payload["display_name"] or "").strip()
        user.display_name = display_name or user.username
    if payload.get("account_type") is not None:
        user.account_type = _normalize_account_type(payload.get("account_type"))
    if payload.get("roles") is not None:
        await db.execute(sa_delete(UserRole).where(UserRole.user_id == user.id))
        for role in await _resolve_roles(db, list(payload["roles"])):
            db.add(UserRole(user_id=user.id, role_id=role.id))
    if payload.get("group_ids") is not None:
        await replace_user_groups(db, user_id=user.id, group_ids=list(payload["group_ids"]))
    after_roles = await _list_role_names(db, user.id)
    record_auth_audit_event(
        db,
        user_id=admin_id,
        action="admin.user.updated",
        resource_type="user",
        resource_id=user.id,
        details={
            "changed_keys": sorted(str(key) for key in payload.keys()),
            "before": before,
            "after": _user_audit_snapshot(user, after_roles),
        },
    )
    await db.commit()
    await db.refresh(user)
    return serialize_user(user, await _list_role_names(db, user.id), await _list_groups(db, user.id))


async def deactivate_user(db: AsyncSession, *, admin_id: str, user_id: str) -> dict[str, Any]:
    if user_id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if _is_bootstrap_admin_user(user):
        raise HTTPException(status_code=400, detail="Bootstrap admin cannot be deactivated")
    before = _user_audit_snapshot(user, await _list_role_names(db, user.id))
    user.is_active = False
    await _revoke_user_auth_material(db, user_id=user.id)
    record_auth_audit_event(
        db,
        user_id=admin_id,
        action="admin.user.deactivated",
        resource_type="user",
        resource_id=user.id,
        details={"before": before, "after": _user_audit_snapshot(user, before["roles"])},
    )
    await db.commit()
    return {"status": "deactivated"}


async def _notify_account_recovery(db: AsyncSession, user_id: str, title: str) -> None:
    from ...team_notification.service import create_notification  # noqa: PLC0415

    try:
        await create_notification(db, user_id=user_id, notification_type="account_recovery", title=title,
                                  body="If you did not ask for this, contact your security team.")
    except Exception:  # noqa: BLE001 - the notice never blocks the recovery itself
        logger.warning("account recovery notice failed", exc_info=True)


async def reset_user_password(db: AsyncSession, *, admin_id: str, user_id: str, password: str) -> dict[str, Any]:
    if user_id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot reset your own password from user management")
    if len(str(password or "")) < 8:
        raise HTTPException(status_code=400, detail="password (min 8 chars) required")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(password)
    # A reset ends every background credential of the account: its devices and paired phones (an account being
    # recovered must not keep an attacker's phone).
    from ...devices.credential import revoke_user_device_grants  # noqa: PLC0415

    await revoke_user_device_grants(db, user_id=user.id)
    record_auth_audit_event(
        db,
        user_id=admin_id,
        action="admin.user.password_reset",
        resource_type="user",
        resource_id=user.id,
        details={"target_username": user.username},
    )
    await _notify_account_recovery(db, user.id, "Your password was reset by an administrator")
    await db.commit()
    return {"status": "password_reset", "user_id": user.id, "admin_id": admin_id}


__all__ = [
    "_notify_account_recovery",
    "create_user",
    "deactivate_user",
    "reset_user_password",
    "update_user",
]
