"""The Workspace policy for workflow proposals (``workflow_proposal_policy``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project

WORKFLOW_PROPOSAL_POLICY_CONFIG_KEY = "workflow_proposal_policy"
WORKFLOW_PROPOSAL_ENABLED_FIELD = "enabled"


class WorkflowProposalPolicyError(ValueError):
    pass


def _section(config: Any) -> dict[str, Any]:
    policy = config.get(WORKFLOW_PROPOSAL_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    return policy if isinstance(policy, dict) else {}


def workflow_proposals_enabled_in(config: Any) -> bool:
    return _section(config).get(WORKFLOW_PROPOSAL_ENABLED_FIELD) is not False


async def workflow_proposals_enabled(db: AsyncSession, project_id: str | None) -> bool:
    if not project_id:
        return True
    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    return workflow_proposals_enabled_in(config)


def normalize_workflow_proposal_policy(value: Any) -> dict[str, Any]:
    section = dict(value) if isinstance(value, dict) else {}
    enabled = section.get(WORKFLOW_PROPOSAL_ENABLED_FIELD)
    if enabled is None:
        return {}
    if not isinstance(enabled, bool):
        raise WorkflowProposalPolicyError(
            f"{WORKFLOW_PROPOSAL_POLICY_CONFIG_KEY}.{WORKFLOW_PROPOSAL_ENABLED_FIELD} must be a boolean"
        )
    return {WORKFLOW_PROPOSAL_ENABLED_FIELD: enabled}


__all__ = [
    "WORKFLOW_PROPOSAL_ENABLED_FIELD",
    "WORKFLOW_PROPOSAL_POLICY_CONFIG_KEY",
    "WorkflowProposalPolicyError",
    "normalize_workflow_proposal_policy",
    "workflow_proposals_enabled",
    "workflow_proposals_enabled_in",
]
