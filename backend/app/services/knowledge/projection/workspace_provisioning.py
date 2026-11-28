"""Governed enablement of Workspace Knowledge. Outcomes are closed states, never server text."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog
from ..access.authorization import AuthorizedWorkspace
from ..evidence_index.postgres_client import application_index_client
from .workspace_classification_default import apply_instance_default_classification

logger = logging.getLogger(__name__)

AUDIT_ACTION = "knowledge.workspace.enable"

STATE_READY = "ready"
STATE_NEEDS_CONFIGURATION = "needs_configuration"


@dataclass(frozen=True, slots=True)
class WorkspaceKnowledgeEnablement:
    state: str
    outcome: str

    def as_dict(self, workspace_id: str) -> dict[str, str]:
        return {"workspace_id": workspace_id, "state": self.state, "outcome": self.outcome}


def _index_state() -> WorkspaceKnowledgeEnablement:
    if application_index_client() is None:
        return WorkspaceKnowledgeEnablement(STATE_NEEDS_CONFIGURATION, "postgres_index_unavailable")
    return WorkspaceKnowledgeEnablement(STATE_READY, "postgres_index")


async def enable_workspace_knowledge(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, actor_id: str
) -> WorkspaceKnowledgeEnablement:
    result = _index_state()
    if result.state == STATE_READY:
        await apply_instance_default_classification(db, project_id=authorized.project_id, actor_id=actor_id)
    db.add(
        AuditLog(
            user_id=actor_id,
            action=AUDIT_ACTION,
            resource_type="workspace",
            resource_id=authorized.project_id,
            details={"state": result.state, "outcome": result.outcome},
        )
    )
    await db.commit()
    return result


__all__ = [
    "AUDIT_ACTION",
    "STATE_NEEDS_CONFIGURATION",
    "STATE_READY",
    "WorkspaceKnowledgeEnablement",
    "enable_workspace_knowledge",
]
