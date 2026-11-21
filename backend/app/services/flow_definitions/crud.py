"""Creating, listing, reading and archiving flow definitions."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import FlowDefinition, FlowDefinitionVersion, User
from ...time_utils import utc_now
from ..access_control import require_existing_workspace
from ..flow_orchestration.flow_agent_reference import with_agent_reference_errors
from ..flow_v2_validation_support import _scan_secret_values
from ..workflow_runs.fragments.store import (
    COMPOSITION_KEY,
    compose_for_save,
    report_with_composition,
    requires_version_id,
)
from .serialize import serialize_flow
from .validation import validate_flow_definition


async def compose_or_refuse(
    db: AsyncSession, definition: dict[str, Any], *, project_id: str | None, require_version_id: bool = True
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """``compose_for_save`` with its refusals as the 422 validation report every save returns."""
    try:
        return await compose_for_save(db, definition, project_id=project_id, require_version_id=require_version_id)
    except ValueError as error:
        errors = getattr(error, "errors", None)
        if not isinstance(errors, list):
            raise
        raise HTTPException(status_code=422, detail={"valid": False, "errors": errors, "warnings": []}) from None


async def _new_flow_identity(db: AsyncSession, payload: dict[str, Any]) -> tuple[str | None, str, str, Any]:
    """The project, key, name and definition of a new flow, refused when invalid or already taken."""
    project_id = str(payload.get("project_id") or "").strip() or None
    await require_existing_workspace(db, project_id)
    key = str(payload.get("key") or "").strip()
    name = str(payload.get("name") or "").strip()
    definition_payload = payload.get("definition") or {}
    if not key or not name:
        raise HTTPException(status_code=422, detail="key and name are required")
    if not isinstance(definition_payload, dict):
        raise HTTPException(status_code=422, detail="definition must be an object")
    duplicate_stmt = select(FlowDefinition).where(FlowDefinition.key == key)
    if project_id:
        duplicate_stmt = duplicate_stmt.where(FlowDefinition.project_id == project_id)
    else:
        duplicate_stmt = duplicate_stmt.where(FlowDefinition.project_id.is_(None))
    if (await db.execute(duplicate_stmt)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Flow definition key already exists for this project")
    return project_id, key, name, definition_payload


def _refuse_invalid_draft(definition: dict[str, Any], validation_report: dict[str, Any]) -> None:
    from ..flow_draft_service import draft_may_be_invalid

    if not validation_report["valid"]:
        secret_errors: list[dict[str, str]] = []
        _scan_secret_values([], definition, secret_errors)
        # An incomplete phased draft is stored with its report; a secret value never is.
        if secret_errors or not draft_may_be_invalid(definition):
            raise HTTPException(status_code=422, detail=validation_report if not secret_errors else {
                "valid": False, "errors": secret_errors, "warnings": []})


async def create_flow_definition(db: AsyncSession, *, current_user: User, payload: dict[str, Any]) -> dict[str, Any]:
    project_id, key, name, definition_payload = await _new_flow_identity(db, payload)
    runtime_settings = dict(payload.get("runtime_settings") or {})
    # A composite source is compiled against its pinned fragments; the compiled graph is what is stored.
    definition, composition = await compose_or_refuse(
        db, dict(definition_payload), project_id=project_id,
        require_version_id=requires_version_id(runtime_settings),
    )
    if composition is not None:
        runtime_settings[COMPOSITION_KEY] = composition
    validation_report = await with_agent_reference_errors(
        db, definition, validate_flow_definition(definition), user_id=current_user.id, project_id=project_id
    )
    validation_report = report_with_composition(validation_report, composition)
    _refuse_invalid_draft(definition, validation_report)
    now = utc_now()
    flow = FlowDefinition(
        id=str(uuid.uuid4()),
        key=key[:180],
        name=name[:220],
        description=str(payload.get("description") or "").strip(),
        project_id=project_id,
        status="draft",
        is_active=bool(payload.get("is_active", True)),
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(flow)
    await db.flush()
    version = FlowDefinitionVersion(
        id=str(uuid.uuid4()),
        flow_id=flow.id,
        version=1,
        status="draft",
        definition_json=definition,
        validation_report=validation_report,
        publish_metadata=dict(payload.get("publish_metadata") or {}),
        runtime_settings=runtime_settings,
        policy_bindings=dict(payload.get("policy_bindings") or {}),
        created_by=current_user.id,
        created_at=now,
    )
    db.add(version)
    await db.flush()
    flow.current_version_id = version.id
    await db.flush()
    return await get_flow_definition(db, flow_id=flow.id)


async def list_flow_definitions(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    include_inactive: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = (
        select(FlowDefinition)
        .options(selectinload(FlowDefinition.versions))
        .order_by(FlowDefinition.updated_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    if project_id:
        stmt = stmt.where(FlowDefinition.project_id == project_id)
    if not include_inactive:
        stmt = stmt.where(FlowDefinition.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_flow(row) for row in rows]


async def get_flow_definition(db: AsyncSession, *, flow_id: str) -> dict[str, Any]:
    flow = (
        await db.execute(
            select(FlowDefinition)
            .where(FlowDefinition.id == flow_id)
            .options(selectinload(FlowDefinition.versions))
        )
    ).scalar_one_or_none()
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow definition not found")
    return serialize_flow(flow, include_versions=True)


async def archive_flow_definition(db: AsyncSession, *, flow_id: str, current_user: User) -> dict[str, Any]:
    flow = await db.get(FlowDefinition, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow definition not found")
    flow.status = "archived"
    flow.is_active = False
    flow.updated_at = utc_now()
    current_version_id = flow.current_version_id
    if current_version_id:
        version = await db.get(FlowDefinitionVersion, current_version_id)
        if version is not None and version.status == "draft":
            version.status = "archived"
            version.publish_metadata = {
                **dict(version.publish_metadata or {}),
                "rejected_by": current_user.id,
                "rejected_at": utc_now().isoformat(),
            }
    await db.flush()
    return await get_flow_definition(db, flow_id=flow.id)


async def next_flow_version_number(db: AsyncSession, *, flow_id: str) -> int:
    value = (
        await db.execute(
            select(func.max(FlowDefinitionVersion.version)).where(FlowDefinitionVersion.flow_id == flow_id)
        )
    ).scalar_one()
    return int(value or 0) + 1
