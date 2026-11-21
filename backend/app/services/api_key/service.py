from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.touch import touch_if_stale
from ...models import APIKey, Role, User, UserRole
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..access_control import require_visible_workspace
from ..security_permissions import user_has_permission
from ..security_scope_contract import allowed_api_key_scopes

API_KEY_PREFIX = "oek_"
ALLOWED_API_KEY_SCOPES = allowed_api_key_scopes()


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key_value() -> tuple[str, str]:
    secret = secrets.token_urlsafe(36)
    raw_key = f"{API_KEY_PREFIX}{secret}"
    return raw_key, raw_key[:12]


def normalize_api_key_scopes(scopes: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    invalid: list[str] = []
    for item in scopes or []:
        scope = str(item or "").strip().lower()
        if not scope:
            continue
        if scope not in ALLOWED_API_KEY_SCOPES:
            invalid.append(scope)
            continue
        if scope not in seen:
            normalized.append(scope)
            seen.add(scope)
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported API key scope: {', '.join(invalid)}",
        )
    return normalized


async def get_user_role_names(db: AsyncSession, user_id: str) -> set[str]:
    result = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return {str(row[0]) for row in result.all()}


def serialize_api_key(entry: APIKey) -> dict:
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "project_id": entry.project_id,
        "name": entry.name,
        "scopes": list(entry.scopes or []),
        "key_prefix": entry.key_prefix,
        "last_used_at": ensure_utc(entry.last_used_at).isoformat() if entry.last_used_at else None,
        "expires_at": ensure_utc(entry.expires_at).isoformat() if entry.expires_at else None,
        "revoked_at": ensure_utc(entry.revoked_at).isoformat() if entry.revoked_at else None,
        "created_at": ensure_utc(entry.created_at).isoformat() if entry.created_at else None,
    }


async def list_api_keys_for_user(db: AsyncSession, current_user: User) -> list[dict]:
    if not await user_has_permission(db, current_user.id, resource="api_keys", action="self_read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key self-service read is not permitted")
    result = await db.execute(
        select(APIKey).where(APIKey.user_id == current_user.id).order_by(APIKey.created_at.desc(), APIKey.name.asc())
    )
    return [serialize_api_key(row) for row in result.scalars().all()]


async def create_api_key_for_user(
    db: AsyncSession,
    *,
    current_user: User,
    name: str,
    scopes: list[str] | None = None,
    project_id: str | None = None,
    expires_at: datetime | None = None,
) -> tuple[APIKey, str]:
    if not await user_has_permission(db, current_user.id, resource="api_keys", action="self_write"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key self-service write is not permitted")
    resolved_name = str(name or "").strip()
    if not resolved_name:
        raise HTTPException(status_code=422, detail="Name is required")
    # An unknown Workspace and one the caller is no member of answer the same 404 (platform admins see every one).
    await require_visible_workspace(db, current_user.id, project_id)
    raw_key, key_prefix = generate_api_key_value()
    entry = APIKey(
        user_id=current_user.id,
        project_id=project_id,
        key_hash=_hash_api_key(raw_key),
        key_prefix=key_prefix,
        name=resolved_name,
        scopes=normalize_api_key_scopes(scopes),
        expires_at=ensure_utc(expires_at) if expires_at else None,
    )
    db.add(entry)
    await db.flush()
    return entry, raw_key


async def revoke_api_key_for_user(db: AsyncSession, *, current_user: User, key_id: str) -> APIKey:
    if not await user_has_permission(db, current_user.id, resource="api_keys", action="self_write"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key self-service write is not permitted")
    entry = (
        await db.execute(select(APIKey).where(APIKey.id == key_id, APIKey.user_id == current_user.id))
    ).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="API key not found")
    if entry.revoked_at is None:
        entry.revoked_at = utc_now()
        await db.flush()
    return entry


async def authenticate_api_key(db: AsyncSession, raw_key: str) -> tuple[User, APIKey]:
    token = str(raw_key or "").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    entry = (await db.execute(select(APIKey).where(APIKey.key_hash == _hash_api_key(token)))).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if entry.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key revoked")
    if entry.expires_at and ensure_utc(entry.expires_at) <= utc_now_aware():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")
    user = await db.get(User, entry.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    # Never waits on the key's row: parallel requests with one key deadlocked the pool (app/db/touch.py).
    await touch_if_stale(db, APIKey, entry.id, entry.last_used_at)
    return user, entry

