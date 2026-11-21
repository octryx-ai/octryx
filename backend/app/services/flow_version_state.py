"""Explicit lifecycle states for flow definition versions.

A flow version is ``draft``, ``published`` or ``archived``. Every operation that takes a
version id (run, publish, unpublish) resolves it here, so an unknown id or a version in the
wrong state is a closed refusal (404/409 with a fixed ``reason``) instead of an unhandled
exception. Reasons never carry ids or free text.

- run: ``draft`` and ``published`` versions with ``schema_version`` 2.0 run (the Flow Builder runs
  drafts as traces); ``archived`` versions are hidden or rejected and do not run.
- publish: ``draft`` or unpublished (``archived`` on an active flow) versions publish; a
  version that is already published, or belongs to a rejected flow, does not.
- unpublish: only a ``published`` version unpublishes.
"""

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
    """A closed refusal for a flow version operation.

    Subclasses ``ValueError`` so runtime callers that already treat runner refusals as
    ``ValueError`` keep working; HTTP routes map it with :meth:`to_http`.
    """

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


def ensure_runnable(version: FlowDefinitionVersion) -> None:
    if version.status == "archived":
        raise FlowVersionStateError(FLOW_VERSION_ARCHIVED)
    if not (dict(version.definition_json or {}).get("nodes") or []):
        raise FlowVersionStateError(FLOW_VERSION_EMPTY)
    if dict(version.definition_json or {}).get("execution_kind") == "phased":
        raise FlowVersionStateError(FLOW_VERSION_PHASED)
    if dict(version.definition_json or {}).get("execution_kind") == FRAGMENT_EXECUTION_KIND:
        raise FlowVersionStateError(FLOW_VERSION_FRAGMENT)
    if str(dict(version.definition_json or {}).get("schema_version") or "").strip() != RUNNABLE_FLOW_SCHEMA_VERSION:
        raise FlowVersionStateError(FLOW_VERSION_UNSUPPORTED_SCHEMA)


def ensure_publishable(version: FlowDefinitionVersion, flow: FlowDefinition) -> None:
    if flow.status == "archived" or not flow.is_active:
        raise FlowVersionStateError(FLOW_ARCHIVED)
    if version.status == "published":
        raise FlowVersionStateError(FLOW_VERSION_ALREADY_PUBLISHED)


def ensure_unpublishable(version: FlowDefinitionVersion) -> None:
    if version.status != "published":
        raise FlowVersionStateError(FLOW_VERSION_NOT_PUBLISHED)
