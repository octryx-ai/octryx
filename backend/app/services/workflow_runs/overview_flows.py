"""The rows of the Workflows list."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models.runtime.flow_definition import FlowDefinition, FlowDefinitionVersion
from ...models.runtime.workflow_run import WorkflowRun
from ...time_utils import utc_now
from ..run_admission.phased_catalog import TEST_FIXTURE_FLAG
from ..run_capability.flow_capability import flow_declared_capability
from .overview_changes import last_change

INACTIVE_FLOW_STATUSES = ("archived",)
# The platform's own acceptance fixture (``attention.fixtures``, published with ``test_fixture``): hidden from the
# Workflows list unless "Show test flows" is on. Display only: nothing about running a flow depends on it.
def is_test_flow(version: Any) -> bool:
    return version is not None and bool(dict(version.publish_metadata or {}).get(TEST_FIXTURE_FLAG))


async def _flow_runs(db: AsyncSession, *, window_days: int) -> dict[str, int]:
    since = utc_now() - timedelta(days=window_days)
    rows = await db.execute(
        select(FlowDefinitionVersion.flow_id, func.count())
        .join(WorkflowRun, WorkflowRun.flow_definition_version_id == FlowDefinitionVersion.id)
        .where(WorkflowRun.created_at >= since)
        .group_by(FlowDefinitionVersion.flow_id)
    )
    return {str(flow_id): int(count) for flow_id, count in rows.all()}


def flow_row(
    flow: FlowDefinition, *, project_name: str | None, used: int, authors: dict[str, str] | None = None
) -> dict[str, Any]:
    versions = sorted(flow.versions, key=lambda item: item.version)
    latest = versions[-1] if versions else None
    version = next((item for item in versions if item.id == flow.current_version_id), latest)
    definition = dict(version.definition_json or {}) if version is not None else {}
    nodes = definition.get("nodes") if isinstance(definition.get("nodes"), list) else []
    return {
        "flow_id": flow.id,
        "key": flow.key,
        "title": flow.name,
        "description": flow.description or "",
        "capability_class": flow_declared_capability(definition).capability_class or "",
        "node_count": len(nodes),
        "scope": project_name or "Global",
        "project_id": flow.project_id,
        "used": used,
        "status": flow.status,
        "version": version.version if version is not None else 0,
        "version_status": version.status if version is not None else "",
        # Switched off by an admin (or an optional shipped workflow not switched on yet): listed with its switch.
        "is_active": bool(flow.is_active),
        "test_flow": is_test_flow(version),
        "execution_kind": "phased" if definition.get("execution_kind") == "phased" else "flow",
        **last_change(versions, names=authors or {}),
    }


async def load_flows(db: AsyncSession, *, project_id: str | None, include_inactive: bool) -> list[FlowDefinition]:
    query = select(FlowDefinition).options(selectinload(FlowDefinition.versions))
    if project_id:
        query = query.where(or_(FlowDefinition.project_id.is_(None), FlowDefinition.project_id == project_id))
    if not include_inactive:
        # A switched-off workflow stays listed, so an admin can switch it on again (an optional shipped workflow
        # starts off); only an archived one leaves the list.
        query = query.where(FlowDefinition.status.not_in(INACTIVE_FLOW_STATUSES))
    return list((await db.execute(query.order_by(FlowDefinition.key))).scalars().all())


async def flow_rows(
    db: AsyncSession, flows: list[FlowDefinition], *, names: dict[str, str], window_days: int,
    authors: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    usage = await _flow_runs(db, window_days=window_days)
    return [
        flow_row(flow, project_name=names.get(flow.project_id or ""), used=usage.get(flow.id, 0), authors=authors)
        for flow in flows
    ]


__all__ = ["flow_row", "flow_rows", "is_test_flow", "load_flows"]
