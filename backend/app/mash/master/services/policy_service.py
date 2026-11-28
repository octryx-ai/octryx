"""MASH policy service — CRUD and changelog integration."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....time_utils import utc_now
from ..models import MashPolicy, MashPolicyAssignment
from ..services.changelog_service import append_change


def _serialize_policy(p: MashPolicy) -> dict[str, Any]:
    return {
        "id": p.id,
        "key": p.key,
        "name": p.name,
        "description": p.description,
        "policy_type": p.policy_type,
        "rules": p.rules,
        "status": p.status,
        "priority": p.priority,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


async def list_policies(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(
        select(MashPolicy).order_by(MashPolicy.priority.desc(), MashPolicy.key)
    )
    return [_serialize_policy(p) for p in result.scalars().all()]


async def create_policy(
    db: AsyncSession,
    *,
    key: str,
    name: str,
    policy_type: str,
    rules: dict[str, Any],
    description: str | None = None,
    priority: int = 0,
) -> dict[str, Any]:
    policy = MashPolicy(
        key=key,
        name=name,
        description=description,
        policy_type=policy_type,
        rules=rules,
        priority=priority,
    )
    db.add(policy)
    await db.flush()

    payload = _serialize_policy(policy)
    await append_change(
        db,
        resource_type="policy",
        resource_key=key,
        resource_version="1",
        change_type="created",
        payload=payload,
    )
    await db.commit()
    return payload


async def update_policy(
    db: AsyncSession,
    *,
    key: str,
    name: str | None = None,
    rules: dict[str, Any] | None = None,
    priority: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    result = await db.execute(select(MashPolicy).where(MashPolicy.key == key))
    policy = result.scalar_one_or_none()
    if not policy:
        raise ValueError(f"Policy '{key}' not found")

    if name is not None:
        policy.name = name
    if rules is not None:
        policy.rules = rules
    if priority is not None:
        policy.priority = priority
    if status is not None:
        policy.status = status

    await db.flush()

    payload = _serialize_policy(policy)
    await append_change(
        db,
        resource_type="policy",
        resource_key=key,
        resource_version="1",
        change_type="updated",
        payload=payload,
    )
    await db.commit()
    return payload


async def delete_policy(db: AsyncSession, *, key: str) -> None:
    result = await db.execute(select(MashPolicy).where(MashPolicy.key == key))
    policy = result.scalar_one_or_none()
    if not policy:
        raise ValueError(f"Policy '{key}' not found")

    # Remove assignments
    await db.execute(
        select(MashPolicyAssignment).where(MashPolicyAssignment.policy_id == policy.id)
    )

    await append_change(
        db,
        resource_type="policy",
        resource_key=key,
        resource_version="1",
        change_type="deleted",
        payload={"key": key},
    )

    await db.delete(policy)
    await db.commit()


async def assign_policy(
    db: AsyncSession,
    *,
    policy_key: str,
    platform_id: str,
) -> dict[str, Any]:
    result = await db.execute(select(MashPolicy).where(MashPolicy.key == policy_key))
    policy = result.scalar_one_or_none()
    if not policy:
        raise ValueError(f"Policy '{policy_key}' not found")

    assignment = MashPolicyAssignment(
        policy_id=policy.id,
        platform_id=platform_id,
        assigned_at=utc_now(),
    )
    db.add(assignment)
    await db.commit()
    return {"policy_key": policy_key, "platform_id": platform_id, "status": "assigned"}
