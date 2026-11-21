"""Read side of admin user management: user lists, role and group names, linked OIDC identities."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import IdentityGroup, IdentityProvider, Role, User, UserGroup, UserIdentity, UserRole
from .admin_identity_group_service import serialize_group

SENSITIVE_CLAIM_KEY_PARTS = ("access_token", "id_token", "refresh_token", "secret", "password", "assertion", "cookie")


def serialize_user(user: User, roles: list[str], groups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email or "",
        "display_name": user.display_name or user.username,
        "account_type": user.account_type or "human",
        "roles": roles,
        "groups": groups or [],
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else "",
    }


async def _list_role_names(db: AsyncSession, user_id: str) -> list[str]:
    role_result = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return [row[0] for row in role_result.all()]


async def _list_groups(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    group_result = await db.execute(
        select(IdentityGroup)
        .join(UserGroup, UserGroup.group_id == IdentityGroup.id)
        .where(UserGroup.user_id == user_id)
    )
    return [serialize_group(group) for group in group_result.scalars().all()]


async def list_users(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    payloads: list[dict[str, Any]] = []
    for user in users:
        payloads.append(serialize_user(user, await _list_role_names(db, user.id), await _list_groups(db, user.id)))
    return payloads


def _sanitize_oidc_claims(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            if any(part in normalized_key for part in SENSITIVE_CLAIM_KEY_PARTS):
                sanitized[str(key)] = "[redacted]"
            else:
                sanitized[str(key)] = _sanitize_oidc_claims(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_oidc_claims(item) for item in value]
    return value


async def list_user_oidc_identities(db: AsyncSession, *, user_id: str) -> list[dict[str, Any]]:
    user = (await db.execute(select(User.id).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows = (
        await db.execute(
            select(UserIdentity, IdentityProvider)
            .join(IdentityProvider, IdentityProvider.id == UserIdentity.provider_id)
            .where(UserIdentity.user_id == user_id)
            .order_by(UserIdentity.last_login_at.desc(), UserIdentity.created_at.desc())
        )
    ).all()
    payload: list[dict[str, Any]] = []
    for identity, provider in rows:
        profile = identity.profile_json if isinstance(identity.profile_json, dict) else {}
        payload.append(
            {
                "id": identity.id,
                "provider_id": provider.id,
                "provider_name": provider.name or "",
                "provider_type": provider.provider_type or "",
                "subject": identity.subject or "",
                "external_email": identity.external_email or "",
                "external_username": identity.external_username or "",
                "external_groups": list(identity.external_groups_json or []),
                "profile": _sanitize_oidc_claims(profile),
                "last_login_at": identity.last_login_at.isoformat() if identity.last_login_at else None,
                "created_at": identity.created_at.isoformat() if identity.created_at else None,
                "updated_at": identity.updated_at.isoformat() if identity.updated_at else None,
            }
        )
    return payload
