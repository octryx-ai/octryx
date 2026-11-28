"""Explicit lifecycle states for flow definition versions. An unknown id or a wrong state is a closed refusal (404/409
with a fixed ``reason``)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FlowDefinition, FlowDefinitionVersion

FLOW_VERSION_NOT_FOUND = "flow_version_not_found"
FLOW_NOT_FOUND = "flow_not_found"
FLOW_VERSION_ARCHIVED = "flow_version_archived"
FLOW_VERSION_EMPTY = "flow_version_empty"
FLOW_VERSION_ALREADY_PUBLISHED = "flow_version_already_published"
FLOW_VERSION_NOT_PUBLISHED = "flow_version_not_published"
FLOW_ARCHIVED = "flow_archived"
# A "Runs in phases" version runs as a workflow run (``services/workflow_runs``), never as a DAG.
FLOW_VERSION_PHASED = "flow_version_phased"
# A fragment is part of a workflow: it is compiled into a composite and never runs on its own.
FLOW_VERSION_FRAGMENT = "flow_version_fragment"
FRAGMENT_EXECUTION_KIND = "phased_fragment"
# Only the 2.0 flow graph runs (``flow_orchestration/dag``).
FLOW_VERSION_UNSUPPORTED_SCHEMA = "flow_version_unsupported_schema"
RUNNABLE_FLOW_SCHEMA_VERSION = "2.0"

_STATUS_BY_REASON: dict[str, int] = {
    FLOW_VERSION_NOT_FOUND: 404,
    FLOW_NOT_FOUND: 404,
    FLOW_VERSION_ARCHIVED: 409,
    FLOW_VERSION_EMPTY: 409,
    FLOW_VERSION_ALREADY_PUBLISHED: 409,
    FLOW_VERSION_NOT_PUBLISHED: 409,
    FLOW_ARCHIVED: 409,
    FLOW_VERSION_PHASED: 409,
    FLOW_VERSION_FRAGMENT: 409,
    FLOW_VERSION_UNSUPPORTED_SCHEMA: 409,
}

_MESSAGE_BY_REASON: dict[str, str] = {
    FLOW_VERSION_NOT_FOUND: "FlowDefinitionVersion not found",
    FLOW_NOT_FOUND: "FlowDefinition not found",
    FLOW_VERSION_ARCHIVED: "FlowDefinitionVersion is archived",
    FLOW_VERSION_EMPTY: "FlowDefinitionVersion has no nodes",
    FLOW_VERSION_ALREADY_PUBLISHED: "FlowDefinitionVersion is already published",
    FLOW_VERSION_NOT_PUBLISHED: "FlowDefinitionVersion is not published",
    FLOW_ARCHIVED: "FlowDefinition is archived",
    FLOW_VERSION_PHASED: "This workflow runs in phases: start it as a workflow run",
    FLOW_VERSION_FRAGMENT: "A fragment is part of a workflow and does not run on its own",
    FLOW_VERSION_UNSUPPORTED_SCHEMA: "Only schema_version 2.0 flow definitions run",
}


class FlowVersionStateError(ValueError):
    # A ``ValueError`` because runtime callers already treat runner refusals as one.

    def __init__(self, reason: str) -> None:
        super().__init__(_MESSAGE_BY_REASON[reason])
        self.reason = reason
        self.status_code = _STATUS_BY_REASON[reason]

    def to_http(self) -> HTTPException:
        return HTTPException(status_code=self.status_code, detail={"reason": self.reason})


async def load_flow_version(db: AsyncSession, version_id: str) -> FlowDefinitionVersion:
    version = await db.get(FlowDefinitionVersion, version_id) if version_id else None
    if version is None:
        raise FlowVersionStateError(FLOW_VERSION_NOT_FOUND)
    return version


async def load_version_flow(db: AsyncSession, version: FlowDefinitionVersion) -> FlowDefinition:
    flow = await db.get(FlowDefinition, version.flow_id)
    if flow is None:
        raise FlowVersionStateError(FLOW_NOT_FOUND)
    return flow


def ensure_publishable(version: FlowDefinitionVersion, flow: FlowDefinition) -> None:
    if flow.status == "archived" or not flow.is_active:
        raise FlowVersionStateError(FLOW_ARCHIVED)
    if version.status == "published":
        raise FlowVersionStateError(FLOW_VERSION_ALREADY_PUBLISHED)


