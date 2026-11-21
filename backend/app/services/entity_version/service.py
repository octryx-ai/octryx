"""Entity version history: create, list and roll back snapshots (serializers in ``serializers.py``)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition, EntityVersion, Role, TaskStep, User, UserRole
from ...time_utils import ensure_utc, utc_now
from .rollback_delegation import assert_rollback_not_delegated
from .serializers import _serialize_agent_definition, _serialize_task_step

SUPPORTED_ENTITY_TYPES = {"agent_definitions", "task_steps"}


def _with_meta(snapshot: dict[str, Any], *, operation: str) -> dict[str, Any]:
    return {**snapshot, "__version_meta__": {"operation": operation}}


async def create_entity_version(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    snapshot: dict[str, Any],
    changed_by: str | None,
    operation: str,
) -> EntityVersion:
    if entity_type not in SUPPORTED_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported entity type")
    next_version = (
        await db.execute(
            select(func.coalesce(func.max(EntityVersion.version), 0) + 1).where(
                EntityVersion.entity_type == entity_type, EntityVersion.entity_id == entity_id
            )
        )
    ).scalar_one()
    entry = EntityVersion(
        entity_type=entity_type,
        entity_id=entity_id,
        version=int(next_version or 1),
        snapshot_json=_with_meta(snapshot, operation=operation),
        changed_by=changed_by,
    )
    db.add(entry)
    await db.flush()
    return entry


def serialize_entity_version(entry: EntityVersion) -> dict[str, Any]:
    return {
        "id": entry.id,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "version": entry.version,
        "snapshot": entry.snapshot_json if isinstance(entry.snapshot_json, dict) else {},
        "changed_by": entry.changed_by,
        "changed_at": ensure_utc(entry.changed_at).isoformat() if entry.changed_at else None,
    }


async def list_entity_versions(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    current_user: User,
) -> list[dict[str, Any]]:
    latest_snapshot = await _latest_snapshot(db, entity_type=entity_type, entity_id=entity_id)
    await _assert_entity_access(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        current_user=current_user,
        snapshot=latest_snapshot,
    )
    result = await db.execute(
        select(EntityVersion)
        .where(EntityVersion.entity_type == entity_type, EntityVersion.entity_id == entity_id)
        .order_by(EntityVersion.version.desc())
    )
    return [serialize_entity_version(row) for row in result.scalars().all()]


async def rollback_entity_version(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    version: int,
    current_user: User,
) -> dict[str, Any]:
    # Entity types with their own fail-closed revision boundary are never
    # restored here; see ``rollback_delegation``. Checked first so no version
    # row is read and no live row is touched for a delegated type.
    assert_rollback_not_delegated(entity_type)
    if entity_type not in SUPPORTED_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported entity type")
    target = (
        await db.execute(
            select(EntityVersion).where(
                EntityVersion.entity_type == entity_type,
                EntityVersion.entity_id == entity_id,
                EntityVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Entity version not found")
    await _assert_entity_access(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        current_user=current_user,
        snapshot=dict(target.snapshot_json or {}),
    )
    snapshot = dict(target.snapshot_json or {})
    snapshot.pop("__version_meta__", None)
    await _restore_snapshot(db, entity_type=entity_type, entity_id=entity_id, snapshot=snapshot)
    await create_entity_version(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        snapshot=snapshot,
        changed_by=current_user.id,
        operation="rollback",
    )
    return {"status": "rolled_back", "entity_type": entity_type, "entity_id": entity_id, "version": version}


async def _assert_entity_access(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    current_user: User,
    snapshot: dict[str, Any] | None = None,
) -> None:
    role_names = await _current_user_roles(db, current_user.id)
    if entity_type == "agent_definitions":
        agent = await db.get(AgentDefinition, entity_id)
        owner_id = agent.owner_id if agent else str((snapshot or {}).get("owner_id") or "").strip() or None
        if owner_id and owner_id != current_user.id and "admin" not in role_names:
            raise HTTPException(status_code=403, detail="Access denied")
        return
    if entity_type == "task_steps":
        if "admin" not in role_names:
            raise HTTPException(status_code=403, detail="Access denied")
        return
    raise HTTPException(status_code=400, detail="Unsupported entity type")


async def _restore_snapshot(db: AsyncSession, *, entity_type: str, entity_id: str, snapshot: dict[str, Any]) -> None:
    # Defense in depth: the same assertion the entry point makes, so no future
    # caller of this writer can reach a delegated aggregate either.
    assert_rollback_not_delegated(entity_type)
    if entity_type == "task_steps":
        entry = await db.get(TaskStep, entity_id)
        if not entry:
            entry = TaskStep(id=entity_id, task_id=str(snapshot.get("task_id") or ""))
            db.add(entry)
        for field in [
            "task_id",
            "position",
            "name",
            "step_type",
            "connector",
            "connector_action",
            "instructions",
            "spawn_strategy",
            "spawn_count",
            "max_fix_attempts",
            "condition_expr",
            "condition_true_step",
            "condition_false_step",
            "agent_timeout_seconds",
            "is_enabled",
        ]:
            setattr(entry, field, snapshot.get(field))
        entry.connector_params_json = __import__("json").dumps(snapshot.get("connector_params") or {})
        entry.runtime_selector_json = __import__("json").dumps(snapshot.get("runtime_selector") or {})
        entry.context_fields_json = __import__("json").dumps(snapshot.get("context_fields") or [])
        entry.allowed_tools_json = __import__("json").dumps(snapshot.get("allowed_tools") or [])
        entry.updated_at = utc_now()
        await db.flush()
        return
    raise HTTPException(status_code=400, detail="Unsupported entity type")


async def _current_user_roles(db: AsyncSession, user_id: str) -> set[str]:
    result = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return {str(row[0]) for row in result.all()}


async def _latest_snapshot(db: AsyncSession, *, entity_type: str, entity_id: str) -> dict[str, Any] | None:
    version = (
        await db.execute(
            select(EntityVersion)
            .where(EntityVersion.entity_type == entity_type, EntityVersion.entity_id == entity_id)
            .order_by(EntityVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not version or not isinstance(version.snapshot_json, dict):
        return None
    return dict(version.snapshot_json)


async def snapshot_agent_definition(
    db: AsyncSession, agent: AgentDefinition, *, changed_by: str | None, operation: str
) -> None:
    await create_entity_version(
        db,
        entity_type="agent_definitions",
        entity_id=agent.id,
        snapshot=_serialize_agent_definition(agent),
        changed_by=changed_by,
        operation=operation,
    )


async def snapshot_task_step(db: AsyncSession, step: TaskStep, *, changed_by: str | None, operation: str) -> None:
    await create_entity_version(
        db,
        entity_type="task_steps",
        entity_id=step.id,
        snapshot=_serialize_task_step(step),
        changed_by=changed_by,
        operation=operation,
    )
