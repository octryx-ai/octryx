"""Admin-panel service helpers for local identity groups."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import IdentityGroup, UserGroup

RLS_ATTRIBUTE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _normalize_name(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_rls_attributes(raw: Any) -> list[dict[str, str]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="RLS attributes must be a list")

    attributes: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Each RLS attribute must be an object")
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        if not key and not value:
            continue
        if not RLS_ATTRIBUTE_KEY_RE.fullmatch(key):
            raise HTTPException(
                status_code=400,
                detail="RLS attribute keys must use letters, numbers, and underscores and start with a letter",
            )
        if not value:
            raise HTTPException(status_code=400, detail=f"RLS attribute '{key}' requires a value")
        if len(value) > 500:
            raise HTTPException(status_code=400, detail=f"RLS attribute '{key}' value is too long")
        normalized_key = key.lower()
        if normalized_key in seen_keys:
            raise HTTPException(status_code=400, detail=f"Duplicate RLS attribute key: {key}")
        seen_keys.add(normalized_key)
        attributes.append({"key": key, "value": value})
    return attributes


def serialize_group(group: IdentityGroup, member_count: int = 0) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description or "",
        "is_active": bool(group.is_active),
        "rls_attributes": normalize_rls_attributes(group.rls_attributes_json),
        "member_count": member_count,
        "created_at": group.created_at.isoformat() if group.created_at else "",
    }


async def list_groups(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(
        select(IdentityGroup, func.count(UserGroup.user_id))
        .outerjoin(UserGroup, UserGroup.group_id == IdentityGroup.id)
        .group_by(IdentityGroup.id)
        .order_by(IdentityGroup.name.asc())
    )
    return [serialize_group(group, int(member_count or 0)) for group, member_count in result.all()]


async def create_group(db: AsyncSession, *, payload: dict[str, Any]) -> dict[str, Any]:
    name = _normalize_name(str(payload.get("name") or ""))
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    existing = (await db.execute(select(IdentityGroup).where(IdentityGroup.name == name))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Group '{name}' already exists")
    group = IdentityGroup(
        id=str(uuid.uuid4()),
        name=name,
        description=str(payload.get("description") or "").strip() or None,
        is_active=bool(payload.get("is_active", True)),
        rls_attributes_json=normalize_rls_attributes(payload.get("rls_attributes")),
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return serialize_group(group)


async def update_group(db: AsyncSession, *, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    group = (await db.execute(select(IdentityGroup).where(IdentityGroup.id == group_id))).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    name = _normalize_name(str(payload.get("name") or ""))
    if name and name != group.name:
        existing = (await db.execute(select(IdentityGroup).where(IdentityGroup.name == name))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail=f"Group '{name}' already exists")
        group.name = name
    if "description" in payload:
        group.description = str(payload.get("description") or "").strip() or None
    if "is_active" in payload:
        group.is_active = bool(payload["is_active"])
    if "rls_attributes" in payload:
        group.rls_attributes_json = normalize_rls_attributes(payload.get("rls_attributes"))
    await db.commit()
    await db.refresh(group)
    member_count = (
        await db.execute(select(func.count()).select_from(UserGroup).where(UserGroup.group_id == group.id))
    ).scalar_one()
    return serialize_group(group, int(member_count or 0))


async def delete_group(db: AsyncSession, *, group_id: str) -> dict[str, Any]:
    group = (await db.execute(select(IdentityGroup).where(IdentityGroup.id == group_id))).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    member_count = (
        await db.execute(select(func.count()).select_from(UserGroup).where(UserGroup.group_id == group.id))
    ).scalar_one()
    if int(member_count or 0) > 0:
        raise HTTPException(status_code=400, detail="Group is assigned to users and cannot be deleted")
    await db.delete(group)
    await db.commit()
    return {"status": "deleted"}


async def resolve_groups(db: AsyncSession, group_ids: list[str]) -> list[IdentityGroup]:
    normalized = [str(group_id or "").strip() for group_id in group_ids if str(group_id or "").strip()]
    if not normalized:
        return []
    result = await db.execute(select(IdentityGroup).where(IdentityGroup.id.in_(normalized)))
    groups_by_id = {group.id: group for group in result.scalars().all()}
    missing = sorted(set(normalized) - set(groups_by_id))
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown group(s): {', '.join(missing)}")
    return [groups_by_id[group_id] for group_id in normalized]


async def replace_user_groups(db: AsyncSession, *, user_id: str, group_ids: list[str]) -> list[dict[str, Any]]:
    groups = await resolve_groups(db, group_ids)
    await db.execute(sa_delete(UserGroup).where(UserGroup.user_id == user_id))
    for group in groups:
        db.add(UserGroup(user_id=user_id, group_id=group.id))
    return [serialize_group(group) for group in groups]
