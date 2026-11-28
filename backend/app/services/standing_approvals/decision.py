"""Always for this Workspace on any pending session approval: grant, then approve."""

from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, ChangePreview
from ...models import Session as AgentSession
from ..approval.errors import approval_already_resolved
from ..session.approval_decision import decide_session_approval
from ..session.turn_approval_state import require_approval_decision_access
from .argument_class import StandingRuleScope, valid_argument_class, valid_tool_name
from .tool_rules import grant_standing_tool_rule

NOT_ELIGIBLE_CODE = "standing_rule_not_eligible"
_DECISION_REASON = "Always for this Workspace"


def _not_eligible() -> HTTPException:
    return HTTPException(status_code=409, detail={"code": NOT_ELIGIBLE_CODE})


async def _tool_scope(db: AsyncSession, approval_id: str) -> StandingRuleScope | None:
    previews = (
        await db.execute(
            select(ChangePreview.preview_json)
            .where(ChangePreview.approval_id == approval_id)
            .order_by(ChangePreview.created_at.desc())
        )
    ).scalars()
    for preview_json in previews:
        try:
            payload = json.loads(preview_json or "{}")
        except json.JSONDecodeError:
            continue
        rule = payload.get("standing_rule") if isinstance(payload, dict) else None
        if not isinstance(rule, dict):
            continue
        tool_name, argument_class = rule.get("tool_name"), rule.get("argument_class")
        if valid_tool_name(tool_name) and valid_argument_class(argument_class):
            return StandingRuleScope(tool_name, argument_class)
    return None


async def _grant(db: AsyncSession, *, approval: Approval, session: AgentSession, decider_id: str) -> None:
    scope = await _tool_scope(db, approval.id)
    if scope is None:
        raise _not_eligible()
    await grant_standing_tool_rule(db, project_id=session.project_id, scope=scope, decider_id=decider_id)


async def decide_approval_always(
    db: AsyncSession, *, approval_id: str, decider_id: str, session_factory=None
) -> Approval:
    approval = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one_or_none()
    if approval is None or not approval.session_id:
        raise HTTPException(status_code=404, detail="Approval not found")
    await require_approval_decision_access(db, approval=approval, user_id=decider_id)
    if approval.status != "pending":
        raise approval_already_resolved()
    session = await db.get(AgentSession, approval.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    await _grant(db, approval=approval, session=session, decider_id=decider_id)
    return await decide_session_approval(
        db,
        approval_id=approval.id,
        decider_id=decider_id,
        decision="approved",
        reason=_DECISION_REASON,
        session_factory=session_factory,
    )


__all__ = ["NOT_ELIGIBLE_CODE", "decide_approval_always"]
