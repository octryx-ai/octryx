"""Append reviewed authoring snapshots without changing the published workflow pointer."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog, FlowDefinition, FlowDefinitionVersion, User
from ..time_utils import utc_now
from .flow_definitions import compose_or_refuse, get_flow_definition, validate_flow_definition
from .flow_orchestration.flow_agent_reference import with_agent_reference_errors
from .flow_v2_validation_support import _scan_secret_values
from .workflow_runs.fragments.store import draft_runtime_settings, is_composite, report_with_composition


def draft_may_be_invalid(definition: dict[str, Any]) -> bool:
    """A workflow that runs in phases is drawn by hand: its draft is saved with its validation report
    even while it is incomplete. Publishing and starting a run still need a valid version (``publish_flow_definition
    _version``, ``engine.start_phased_run``). A flow graph's draft can run as a trace, so it stays refused."""
    from .workflow_runs.graph import is_phased_definition

    return is_phased_definition(definition)


async def _checked_draft_definition(
    db: AsyncSession, *, flow_id: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    definition = payload.get("definition")
    if not isinstance(definition, dict):
        raise HTTPException(422, "definition must be an object")
    composition = None
    if is_composite(definition):
        # A composite source is compiled against its pinned fragments before it is validated and stored.
        scope = (await db.execute(select(FlowDefinition.project_id).where(FlowDefinition.id == flow_id))).first()
        if scope is None:
            raise HTTPException(404, "Flow definition not found")
        definition, composition = await compose_or_refuse(db, definition, project_id=scope[0])
    report = report_with_composition(validate_flow_definition(definition), composition)
    secret_errors: list[dict[str, str]] = []
    _scan_secret_values([], definition, secret_errors)
    if secret_errors:
        raise HTTPException(422, {"valid": False, "errors": secret_errors})
    if not report["valid"] and not draft_may_be_invalid(definition):
        raise HTTPException(422, report)
    return definition, composition, report


def _checked_name_and_description(payload: dict[str, Any]) -> tuple[str, str]:
    name = payload.get("name")
    description = payload.get("description", "")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 220:
        raise HTTPException(422, "name must contain 1 to 220 characters")
    if not isinstance(description, str):
        raise HTTPException(422, "description must be a string")
    return name, description


async def _locked_open_flow(db: AsyncSession, flow_id: str) -> FlowDefinition:
    flow = (await db.execute(
        select(FlowDefinition).where(FlowDefinition.id == flow_id).with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if flow is None:
        raise HTTPException(404, "Flow definition not found")
    if flow.status == "archived" or not flow.is_active:
        raise HTTPException(409, "Archived workflows cannot receive draft revisions")
    return flow


async def _expected_latest_version(db: AsyncSession, flow_id: str, expected: str) -> FlowDefinitionVersion:
    latest = (await db.execute(
        select(FlowDefinitionVersion).where(FlowDefinitionVersion.flow_id == flow_id)
        .order_by(FlowDefinitionVersion.version.desc()).limit(1)
    )).scalar_one_or_none()
    if latest is None or latest.id != expected:
        raise HTTPException(409, "Workflow changed. Reload the latest revision before saving.")
    return latest


async def save_flow_draft(
    db: AsyncSession, *, flow_id: str, current_user: User, payload: dict[str, Any]
) -> dict[str, Any]:
    """Require the latest revision as a precondition; never mutate an existing version."""
    expected = payload.get("expected_latest_version_id")
    if not isinstance(expected, str) or not expected:
        raise HTTPException(422, "expected_latest_version_id is required")
    definition, composition, report = await _checked_draft_definition(db, flow_id=flow_id, payload=payload)
    name, description = _checked_name_and_description(payload)
    flow = await _locked_open_flow(db, flow_id)
    # A draft may only name agents this workflow can run.
    report = await with_agent_reference_errors(
        db, definition, report, user_id=current_user.id, project_id=flow.project_id
    )
    if not report["valid"] and not draft_may_be_invalid(definition):
        raise HTTPException(422, report)
    latest = await _expected_latest_version(db, flow_id, expected)
    now = utc_now()
    version_id = str(uuid.uuid4())
    values = {"name": name.strip(), "description": description.strip(), "updated_at": now}
    # Published consumers stay pinned until explicit publication. Draft-only workflows may
    # move their default pointer; manual authoring runs always carry an explicit version id.
    if flow.status != "published":
        values["current_version_id"] = version_id
    claimed = await db.execute(
        update(FlowDefinition).where(
            FlowDefinition.id == flow_id, FlowDefinition.updated_at == flow.updated_at
        ).values(**values).execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        raise HTTPException(409, "Workflow changed. Reload the latest revision before saving.")
    db.add(FlowDefinitionVersion(
        id=version_id, flow_id=flow_id, version=latest.version + 1, status="draft",
        definition_json=copy.deepcopy(definition), validation_report=report,
        runtime_settings=draft_runtime_settings(copy.deepcopy(latest.runtime_settings or {}), definition,
                                                copy.deepcopy(composition)),
        policy_bindings=copy.deepcopy(latest.policy_bindings or {}),
        publish_metadata={}, created_by=current_user.id, created_at=now,
    ))
    db.add(AuditLog(
        user_id=current_user.id, action="flow_draft_saved", resource_type="flow_definition",
        resource_id=flow_id, details={"version_id": version_id, "base_version_id": expected},
    ))
    await db.flush()
    await db.refresh(flow, attribute_names=["name", "description", "updated_at", "current_version_id", "versions"])
    return await get_flow_definition(db, flow_id=flow_id)
