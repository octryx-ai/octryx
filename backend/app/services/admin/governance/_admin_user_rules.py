"""Validation rules of admin user management: account types, role names and the protected bootstrap admin."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Role, User

ACCOUNT_TYPES = {"human", "technical"}
BOOTSTRAP_ADMIN_USERNAME = "admin"


async def _resolve_roles(db: AsyncSession, role_names: list[str]) -> list[Role]:
    # A user may hold several roles (SSO group mappings assign more than one); keep them all.
    normalized = list(dict.fromkeys(_normalized_role_names(role_names)))
    if not normalized:
        return []
    result = await db.execute(select(Role).where(Role.name.in_(normalized)))
    roles_by_name = {role.name: role for role in result.scalars().all()}
    missing = sorted(set(normalized) - set(roles_by_name))
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown role(s): {', '.join(missing)}")
    return [roles_by_name[name] for name in normalized]


def _normalize_account_type(value: Any) -> str:
    account_type = str(value or "human").strip().lower()
    if account_type not in ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail="Account type must be 'human' or 'technical'")
    return account_type


def _normalized_role_names(role_names: list[str]) -> list[str]:
    return [str(role_name or "").strip().lower() for role_name in role_names if str(role_name or "").strip()]


def _is_bootstrap_admin_user(user: User) -> bool:
    return user.username == BOOTSTRAP_ADMIN_USERNAME


def _validate_bootstrap_admin_update(user: User, payload: dict[str, Any]) -> None:
    if not _is_bootstrap_admin_user(user):
        return
    if payload.get("username") is not None and str(payload.get("username") or "").strip() != BOOTSTRAP_ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="Bootstrap admin username is protected")
    if payload.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Bootstrap admin cannot be deactivated")
    if payload.get("account_type") is not None and _normalize_account_type(payload.get("account_type")) != "human":
        raise HTTPException(status_code=400, detail="Bootstrap admin account type is protected")
    if payload.get("roles") is not None and _normalized_role_names(list(payload["roles"])) != ["admin"]:
        raise HTTPException(status_code=400, detail="Bootstrap admin must keep the admin role")
