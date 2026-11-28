"""Publishing a draft flow definition version."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FlowDefinition, FlowDefinitionVersion, User
from ...time_utils import utc_now
from ..flow_version_state import FlowVersionStateError, ensure_publishable, load_flow_version, load_version_flow
from ..workflow_runs.fragments.store import (
    composition_of,
    is_fragment,
    lock_version_for_publish,
    report_with_composition,
    verify_composition_at_publish,
)
from .crud import get_flow_definition
from .validation import validate_flow_definition


async def _load_publishable(
    db: AsyncSession, version_id: str
) -> tuple[FlowDefinitionVersion, FlowDefinition, bool, bool]:
    try:
        version = await load_flow_version(db, version_id)
        flow = await load_version_flow(db, version)
        fragment = is_fragment(dict(version.definition_json or {}))
        composite = composition_of(version) is not None
        if fragment or composite:
            # State check, pin check and publish are one serialised step under concurrent publishes.
            version = await lock_version_for_publish(db, version)
        ensure_publishable(version, flow)
    except FlowVersionStateError as error:
        raise error.to_http() from None
    return version, flow, fragment, composite


async def _publish_report(
    db: AsyncSession,
    version: FlowDefinitionVersion,
    flow: FlowDefinition,
    current_user: User,
    *,
    composite: bool,
) -> dict[str, Any]:
    definition = dict(version.definition_json or {})
    report = validate_flow_definition(definition)
    from ..workflow_runs.phase_agents import with_phase_agent_errors

    report = await with_phase_agent_errors(db, definition, report)
    if composite:
        composition_errors = await verify_composition_at_publish(db, version, project_id=flow.project_id)
        if composition_errors:
            report = {**report, "valid": False, "errors": list(report.get("errors") or []) + composition_errors}
        report = report_with_composition(report, composition_of(version))
    return report


async def publish_flow_definition_version(
    db: AsyncSession,
    *,
    version_id: str,
    current_user: User,
    publish_metadata: dict[str, Any] | None = None,
    shipped: bool = False,
) -> dict[str, Any]:
    """Publish a draft. A phased workflow or fragment needs a second admin (``flow_publish_review``); ``shipped``
    marks the platform's own publish of content it ships (seeders, fixtures), never a request's."""
    from ..flow_publish_review import require_publish_four_eyes

    version, flow, fragment, composite = await _load_publishable(db, version_id)
    four_eyes = await require_publish_four_eyes(db, version, current_user, shipped=shipped)
    report = await _publish_report(db, version, flow, current_user, composite=composite)
    if not report["valid"]:
        version.validation_report = report
        await db.flush()
        raise HTTPException(status_code=422, detail=report)
    version.status = "published"
    version.validation_report = report
    version.publish_metadata = {
        **dict(version.publish_metadata or {}),
        **(publish_metadata or {}),
        **four_eyes,  # after the request's metadata: a request body never states its own approval
    }
    version.published_by = current_user.id
    version.published_at = utc_now()
    flow.status = "published"
    flow.current_version_id = version.id
    flow.updated_at = utc_now()
    await db.flush()
    return await get_flow_definition(db, flow_id=version.flow_id)
