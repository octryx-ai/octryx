"""Admin-panel service helpers for user-owned API keys."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import APIKey, User
from ....time_utils import utc_now
from ...api_key.service import create_api_key_for_user, serialize_api_key


async def _get_user(db: AsyncSession, user_id: str) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def list_user_api_keys(db: AsyncSession, *, user_id: str) -> list[dict[str, Any]]:
    await _get_user(db, user_id)
    rows = await db.execute(
        select(APIKey).where(APIKey.user_id == user_id).order_by(APIKey.created_at.desc(), APIKey.name.asc())
    )
    return [serialize_api_key(row) for row in rows.scalars().all()]


async def create_user_api_key(db: AsyncSession, *, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    user = await _get_user(db, user_id)
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Cannot create API key for inactive user")
    entry, raw_key = await create_api_key_for_user(
        db,
        current_user=user,
        name=str(payload.get("name") or ""),
        scopes=list(payload.get("scopes") or []),
        project_id=payload.get("project_id"),
        expires_at=payload.get("expires_at"),
    )
    await db.commit()
    await db.refresh(entry)
    result = serialize_api_key(entry)
    result["api_key"] = raw_key
    return result


async def revoke_user_api_key(db: AsyncSession, *, user_id: str, key_id: str) -> dict[str, Any]:
    await _get_user(db, user_id)
    entry = (
        await db.execute(select(APIKey).where(APIKey.id == key_id, APIKey.user_id == user_id))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if entry.revoked_at is None:
        entry.revoked_at = utc_now()
    await db.commit()
    await db.refresh(entry)
    return serialize_api_key(entry)
