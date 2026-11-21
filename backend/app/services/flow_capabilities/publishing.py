"""Hiding a published workflow capability and auditing its exposure."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, FlowDefinition, FlowDefinitionVersion, User
from ...time_utils import utc_now
from ..flow_version_state import FlowVersionStateError, ensure_unpublishable, load_flow_version, load_version_flow
from .naming import workflow_tool_name_for_key


async def unpublish_flow_definition_version(
    db: AsyncSession,
    *,
    version_id: str,
    current_user: User,
    reason: str | None = None,
) -> dict[str, Any]:
    try:
        version = await load_flow_version(db, version_id)
        flow = await load_version_flow(db, version)
        ensure_unpublishable(version)
    except FlowVersionStateError as error:
        raise error.to_http() from None
    version.status = "archived"
    version.publish_metadata = {
        **dict(version.publish_metadata or {}),
        "capability_enabled": False,
        "llm_visible": False,
        "hidden_by": current_user.id,
        "hidden_at": utc_now().isoformat(),
        "hidden_reason": str(reason or "Unpublished from Flow Builder").strip(),
    }
    if flow.current_version_id == version.id:
        flow.status = "draft"
        flow.current_version_id = None
        latest_draft = (
            await db.execute(
                select(FlowDefinitionVersion)
                .where(
                    FlowDefinitionVersion.flow_id == flow.id,
                    FlowDefinitionVersion.status == "draft",
                )
                .order_by(FlowDefinitionVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_draft is not None:
            flow.current_version_id = latest_draft.id
        flow.updated_at = utc_now()
    await _audit_definition_event(
        db,
        current_user=current_user,
        action="workflow.capability_hidden",
        flow=flow,
        version=version,
        details={"reason": reason or "Unpublished from Flow Builder"},
    )
    await db.flush()
    from ..flow_definitions import get_flow_definition

    return await get_flow_definition(db, flow_id=flow.id)


async def audit_flow_capability_published(
    db: AsyncSession,
    *,
    current_user: User,
    flow: FlowDefinition,
    version: FlowDefinitionVersion,
    metadata: dict[str, Any],
) -> None:
    await _audit_definition_event(
        db,
        current_user=current_user,
        action="workflow.capability_exposed",
        flow=flow,
        version=version,
        details={
            "tool_name": workflow_tool_name_for_key(flow.key, flow.name),
            "llm_visible": bool(metadata.get("llm_visible", True)),
            "capability_enabled": bool(metadata.get("capability_enabled", True)),
            "allowed_projects": (
                metadata.get("allowed_projects") if isinstance(metadata.get("allowed_projects"), list) else []
            ),
        },
    )


async def _audit_definition_event(
    db: AsyncSession,
    *,
    current_user: User,
    action: str,
    flow: FlowDefinition,
    version: FlowDefinitionVersion,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=action,
            resource_type="flow_definition",
            resource_id=flow.id,
            details={
                "flow_id": flow.id,
                "flow_key": flow.key,
                "version_id": version.id,
                "version": version.version,
                "project_id": flow.project_id,
                **(details or {}),
            },
        )
    )
    await db.flush()
