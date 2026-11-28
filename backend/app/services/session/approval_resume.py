"""Resume what a decided session approval paused: a held workflow proposal, or a device or runner thread."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...db import core as db_core
from ...models import Approval
from ...models import Session as AgentSession
from ..workflow_routing.proposal_approval import resume_workflow_proposal_approval

logger = logging.getLogger(__name__)

DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"


async def resume_decided_approval(
    db: AsyncSession,
    *,
    session: AgentSession,
    approval: Approval,
    decision: str,
    session_factory=None,
) -> None:
    factory = session_factory or db_core.async_session_factory
    if await resume_workflow_proposal_approval(
        db, session=session, approval=approval, decision=decision, session_factory=factory
    ):
        return
    from ..devices.agent_runtime import resume_device_thread

    await resume_device_thread(db, session=session, approval=approval, decision=decision)


__all__ = [
    "DECISION_APPROVED",
    "DECISION_REJECTED",
    "resume_decided_approval",
]
