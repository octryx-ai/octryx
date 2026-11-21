"""Four-eyes publish of a platform agent revision.

A platform agent (Assistant, Engineer, Reviewer) shapes every chat turn and every workflow phase, so its
revision is published only by a global admin who did not author it, unless the platform's approval rule
allows self-approval (the same ``decide_four_eyes`` every workflow publish asks). The approver is recorded on
the revision. Every other agent keeps the existing publish rule.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition
from ...models.agent.agent_definition_revision import AgentDefinitionRevision
from ...time_utils import utc_now
from ..admin.governance.admin_access_service import is_global_admin
from ..governance.four_eyes import FOUR_EYES_PASSING_STATUSES, decide_four_eyes, record_self_approval_audit
from .catalog import is_platform_agent_key

REFUSAL_ADMIN_REQUIRED = "platform_agent_admin_required"
REFUSAL_FOUR_EYES = "platform_agent_four_eyes_required"
RESOURCE_TYPE = "agent_definition_revision"


async def check_platform_agent_publish(
    db: AsyncSession, *, revision: AgentDefinitionRevision, publisher_id: str
) -> None:
    """Refuse (403, typed) or record the approver; a no-op for agents that are not platform agents."""
    definition = await db.get(AgentDefinition, revision.definition_id)
    if definition is None or not is_platform_agent_key(definition.builtin_key):
        return
    if not await is_global_admin(db, publisher_id):
        raise HTTPException(status_code=403, detail={"code": REFUSAL_ADMIN_REQUIRED})
    decision = await decide_four_eyes(db, revision.created_by, publisher_id)
    if decision.status not in FOUR_EYES_PASSING_STATUSES:
        raise HTTPException(status_code=403, detail={"code": REFUSAL_FOUR_EYES, "four_eyes": decision.status})
    record_self_approval_audit(
        db, decision, resource_type=RESOURCE_TYPE, resource_id=revision.id, approval_id=revision.id
    )
    revision.approved_by = publisher_id
    revision.approved_at = utc_now()
