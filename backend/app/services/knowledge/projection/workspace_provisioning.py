"""Governed enablement of Workspace Knowledge.

A Workspace author asks to enable Knowledge; this checks that the Evidence index is available
(the application's PostgreSQL, whose index tables are shared and keyed by Workspace, so there is
nothing to create per Workspace) and one audit row records who asked and the closed outcome.

A ready enablement also classifies a still unclassified Workspace with the Instance's opt-in default
data classification, once (``workspace_classification_default``), so its remote Knowledge models (the
reranker) are admitted by the data-policy gate.

Outcomes are closed states, never server text: ``ready`` (``postgres_index``) or
``needs_configuration`` (``postgres_index_unavailable``: the application database is not PostgreSQL).
"""

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
    """The closed result of one enable request."""

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
    """Check that the Evidence index is available for the Workspace and audit the attempt."""
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
