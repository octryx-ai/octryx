"""The per-connection confirmation session behind ``workflow_select`` / ``workflow_confirm``.

One confirmation covers one workflow for one connection: the launcher session key or, without
one, the OAuth grant. The confirmation lives on an external shadow session of that scope, and its
latest approval decides whether the workflow is selected, rejected or still needs confirming.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval, Session, User
from .agent_gateway.confirmation import (
    CONFIRMATION_ACTION_PREFIX,
    CONFIRMATION_PURPOSE,
    confirmation_scope_for_grant,
    confirmation_scope_for_session,
)
from .knowledge.episodes.policy import public_origin, session_link
from .mcp_external_session import create_external_shadow_session
from .mcp_governed_knowledge import McpCaller


def _confirmation_scope(caller: McpCaller) -> str:
    if caller.session_key:
        return confirmation_scope_for_session(caller.session_key)
    return confirmation_scope_for_grant(caller.grant_id)


async def _confirmation_session(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, workflow_key: str, create: bool
) -> Session | None:
    scope = _confirmation_scope(caller)
    session = (
        await db.execute(
            select(Session)
            .where(
                Session.user_id == user.id,
                Session.project_id == workspace_id,
                Session.agent_type == "external_agent",
                Session.metadata_["purpose"].as_string() == CONFIRMATION_PURPOSE,
                Session.metadata_["confirmation_scope"].as_string() == scope,
                Session.metadata_["workflow_key"].as_string() == workflow_key,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if session is None and create:
        session = await create_external_shadow_session(
            db,
            user=user,
            project_id=workspace_id,
            grant_id=caller.grant_id,
            source_metadata={
                "purpose": CONFIRMATION_PURPOSE,
                "confirmation_scope": scope,
                "workflow_key": workflow_key,
                "summary": f"Confirmation of workflow '{workflow_key}' for an external agent session.",
            },
        )
    return session


async def _latest_confirmation(db: AsyncSession, session: Session, workflow_key: str) -> Approval | None:
    return (
        (
            await db.execute(
                select(Approval)
                .where(Approval.session_id == session.id, Approval.action == CONFIRMATION_ACTION_PREFIX + workflow_key)
                .order_by(Approval.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


def _confirmation_answer(approval: Approval, session: Session, external: dict[str, Any]) -> dict[str, Any]:
    origin = public_origin()
    return {
        "state": "needs_confirmation",
        "reason": "workflow_requires_confirmation",
        "approval_id": approval.id,
        "workflow": external,
        "confirm": {
            "in_platform": session_link(origin, session.id) if origin else None,
            "in_claude_code": {"tool": "workflow_confirm", "arguments": {"approval_id": approval.id}},
        },
    }
