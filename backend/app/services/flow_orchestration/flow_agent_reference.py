"""Which agent a workflow node may name.

A workflow ``agent_step`` or ``supervisor`` node names an agent by ``config.agent_definition_id``.
The reference is checked when a draft is saved, a workflow is created or published, and again
right before the node runs (an agent can be deactivated after publication):

* the agent must exist and belong to the acting user, the same owner scope the agent panel and
  chat use. An unknown id and another owner's agent fail identically (``agent_not_accessible``)
  so the check never reveals whether an inaccessible agent exists;
* the agent must be active (``agent_inactive``);
* scope: a Global agent (no workspace) may run in any workflow; a workspace agent only in a
  workflow of the same workspace, never in a Global workflow (``agent_out_of_scope``);
* validation also asks the governed resolver whether the platform would execute the agent now
  (published execution mode without a published revision → ``agent_needs_publication``, an
  invalid mode → ``agent_execution_not_configured``); the row alone does not prove that.

``POST /api/v1/flows/validate`` passes its context explicitly (``flow_id`` of a stored workflow or
an explicit ``project_id``, ``null`` meaning Global); without either, a definition that names an
agent gets the blocking ``agent_reference_context_required`` instead of a guessed workspace.

Messages are fixed server text: they never carry names or ids of agents the caller cannot read.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_execution_states import REFUSAL_STATUSES, STATUS_INACTIVE, STATUS_NEEDS_PUBLICATION

from ...models import AgentDefinition, FlowDefinition
from ..agent_definition_execution import resolve_agent_definition_for_execution
from ..agent_visibility import visible_agent_clause
from ..runtime_failure_errors import ClassifiedFlowError

AGENT_NODE_TYPES = frozenset({"agent_step", "supervisor"})
AGENT_NOT_ACCESSIBLE = "agent_not_accessible"
AGENT_INACTIVE = "agent_inactive"
AGENT_OUT_OF_SCOPE = "agent_out_of_scope"
AGENT_NEEDS_PUBLICATION = "agent_needs_publication"
AGENT_EXECUTION_NOT_CONFIGURED = "agent_execution_not_configured"
CONTEXT_REQUIRED = "agent_reference_context_required"

REFERENCE_MESSAGES = {
    AGENT_NOT_ACCESSIBLE: "the selected agent does not exist or is not available to you",
    AGENT_INACTIVE: "the selected agent is inactive; activate it on its agent page",
    AGENT_OUT_OF_SCOPE: "the selected agent belongs to a different workspace than this workflow",
    AGENT_NEEDS_PUBLICATION: "the selected agent has no published revision, which this platform requires to run it",
    AGENT_EXECUTION_NOT_CONFIGURED: "the platform's agent execution mode is not configured, so no agent can run",
}


class FlowAgentReferenceError(ClassifiedFlowError):
    """An agent reference the workflow may not run; a configuration error of the workflow."""

    def __init__(self, code: str) -> None:
        super().__init__(code, category="input_contract_error", required_action="fix_workflow_configuration")


def agent_references(definition: dict[str, Any]) -> list[tuple[str, str]]:
    """``(node_id, agent_definition_id)`` for every agent node that names an agent."""
    references: list[tuple[str, str]] = []
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type") or "").strip() not in AGENT_NODE_TYPES:
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        agent_id = str(config.get("agent_definition_id") or "").strip()
        if agent_id:
            references.append((str(node.get("id") or "").strip(), agent_id))
    return references


async def check_flow_agent_reference(
    db: AsyncSession, *, definition_id: str, user_id: str, flow_project_id: str | None
) -> AgentDefinition:
    """The referenced agent row, or :class:`FlowAgentReferenceError` with a closed code."""
    agent = (
        await db.execute(
            select(AgentDefinition).where(
                AgentDefinition.id == str(definition_id or "").strip(), await visible_agent_clause(db, user_id)
            )
        )
    ).scalar_one_or_none()
    if agent is None:
        raise FlowAgentReferenceError(AGENT_NOT_ACCESSIBLE)
    if not agent.is_active:
        raise FlowAgentReferenceError(AGENT_INACTIVE)
    if agent.project_id and agent.project_id != (flow_project_id or None):
        raise FlowAgentReferenceError(AGENT_OUT_OF_SCOPE)
    return agent


def resolution_reference_code(status: str) -> str:
    """The reference code of a refused resolution; inactive stays ``agent_inactive``."""
    if status == STATUS_INACTIVE:
        return AGENT_INACTIVE
    if status == STATUS_NEEDS_PUBLICATION:
        return AGENT_NEEDS_PUBLICATION
    return AGENT_EXECUTION_NOT_CONFIGURED


async def flow_agent_reference_errors(
    db: AsyncSession, definition: dict[str, Any], *, user_id: str, project_id: str | None
) -> list[dict[str, str]]:
    """Validation errors (``{code, message}``) for every agent node the workflow may not run."""
    errors: list[dict[str, str]] = []
    for node_id, agent_id in agent_references(definition):
        try:
            await check_flow_agent_reference(db, definition_id=agent_id, user_id=user_id, flow_project_id=project_id)
            resolution = await resolve_agent_definition_for_execution(
                db, definition_id=agent_id, visible_to_user_id=user_id
            )
            if resolution.status in REFUSAL_STATUSES:
                raise FlowAgentReferenceError(resolution_reference_code(resolution.status))
        except FlowAgentReferenceError as refusal:
            errors.append({"code": refusal.code, "message": f"{node_id}: {REFERENCE_MESSAGES[refusal.code]}."})
    return errors


async def with_agent_reference_errors(
    db: AsyncSession, definition: dict[str, Any], report: dict[str, Any], *, user_id: str, project_id: str | None
) -> dict[str, Any]:
    """``report`` with the agent reference errors added (and ``valid`` false when there are any)."""
    errors = await flow_agent_reference_errors(db, definition, user_id=user_id, project_id=project_id)
    if not errors:
        return report
    return {**report, "valid": False, "errors": [*list(report.get("errors") or []), *errors]}


async def with_agent_reference_errors_for_request(
    db: AsyncSession, definition: dict[str, Any], report: dict[str, Any], payload: dict[str, Any], *, user_id: str
) -> dict[str, Any]:
    """The validate route's report with agent reference errors for its explicit context."""
    if payload.get("flow_id"):
        flow = await db.get(FlowDefinition, str(payload["flow_id"]))
        if flow is None:
            raise HTTPException(status_code=404, detail="Flow definition not found")
        return await with_agent_reference_errors(db, definition, report, user_id=user_id, project_id=flow.project_id)
    if "project_id" in payload:
        project_id = str(payload.get("project_id") or "").strip() or None
        return await with_agent_reference_errors(db, definition, report, user_id=user_id, project_id=project_id)
    if not agent_references(definition):
        return report
    message = "Validate from the workflow editor (flow_id) or pass project_id to check its agent references."
    error = {"code": CONTEXT_REQUIRED, "message": message}
    return {**report, "valid": False, "errors": [*list(report.get("errors") or []), error]}


__all__ = [
    "AGENT_EXECUTION_NOT_CONFIGURED",
    "AGENT_INACTIVE",
    "AGENT_NEEDS_PUBLICATION",
    "AGENT_NODE_TYPES",
    "AGENT_NOT_ACCESSIBLE",
    "AGENT_OUT_OF_SCOPE",
    "CONTEXT_REQUIRED",
    "FlowAgentReferenceError",
    "agent_references",
    "check_flow_agent_reference",
    "flow_agent_reference_errors",
    "resolution_reference_code",
    "with_agent_reference_errors",
    "with_agent_reference_errors_for_request",
]
