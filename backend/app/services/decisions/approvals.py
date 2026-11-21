"""The approval lifecycle as decision records (O2): requested → approved / rejected / expired / cancelled.

A new ``approvals`` row (any producer: tool approval gate, workflow proposals, governance publish reviews, flows)
records ``needs_approval`` through a mapper listener, so no producer can skip it. A decision records its outcome
from :func:`record_approval_decided`, called by the one compare-and-set every decider goes through
(``approval.resolution_service.decide_pending_approval``), with who decided and under which approval rule. The
request's reason stays on the ``needs_approval`` record; the decider's note goes on the outcome record.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, PolicyDecisionLog, Session, User
from ..governance.approval_rule import APPROVAL_RULE_LABELS, load_approval_rule
from ..observability import agent_metrics
from .recorder import (
    APPROVAL_OUTCOMES,
    GATE_GOVERNANCE_REVIEW,
    GATE_TOOL_APPROVAL,
    OUTCOME_NEEDS_APPROVAL,
    build_gate_record,
)

_LOG = PolicyDecisionLog.__table__


def approval_gate(approval: Approval) -> str:
    """Session and task-run approvals hold a run; the others are governance reviews (publish, resume, …)."""
    return GATE_TOOL_APPROVAL if approval.session_id or approval.task_run_id else GATE_GOVERNANCE_REVIEW


def _user_label(connection: Any, user_id: str | None) -> str:
    if not user_id:
        return "system"
    name = connection.execute(select(User.username).where(User.id == user_id)).scalar_one_or_none()
    return name or user_id


def _workspace(connection: Any, approval: Approval) -> str | None:
    if approval.workspace_id or not approval.session_id:
        return approval.workspace_id
    return connection.execute(select(Session.project_id).where(Session.id == approval.session_id)).scalar_one_or_none()


@event.listens_for(Approval, "after_insert")
def _approval_inserted(_mapper: Any, connection: Any, approval: Approval) -> None:
    common = {
        "gate": approval_gate(approval),
        "action": "approval",
        "resource": approval.action or "",
        "workspace_id": _workspace(connection, approval),
        "session_id": approval.session_id,
        "approval_id": approval.id,
    }
    # Written in the inserting transaction: the record exists exactly when the approval does.
    connection.execute(_LOG.insert().values(**build_gate_record(
        outcome=OUTCOME_NEEDS_APPROVAL, principal=_user_label(connection, approval.requested_by),
        reason=approval.reason, created_at=approval.created_at, **common,
    )))
    if approval.status in APPROVAL_OUTCOMES:  # created already decided (e.g. an adoption approved in one step)
        connection.execute(_LOG.insert().values(**build_gate_record(
            outcome=approval.status, principal=_user_label(connection, approval.approved_by),
            actor_id=approval.approved_by, rule="approved when created", created_at=approval.resolved_at, **common,
        )))


async def _label(db: AsyncSession, user_id: str | None) -> str:
    if not user_id:
        return "system"
    return (await db.execute(select(User.username).where(User.id == user_id))).scalar_one_or_none() or user_id


async def record_approval_decided(db: AsyncSession, approval: Approval) -> None:
    """Record the decision just made on ``approval`` (its status, decider, note) under the approval rule."""
    if approval.status not in APPROVAL_OUTCOMES:
        return
    agent_metrics.on_commit(db, agent_metrics.approval_decided(approval))
    rule = APPROVAL_RULE_LABELS.get(await load_approval_rule(db), "")
    if approval.approved_by is None:
        rule = "time limit reached" if approval.status == "expired" else rule
    elif approval.approved_by == approval.requested_by:
        rule = f"{rule} · self-approval" if rule else "self-approval"
    workspace_id = approval.workspace_id
    if workspace_id is None and approval.session_id:
        session = await db.get(Session, approval.session_id)
        workspace_id = session.project_id if session is not None else None
    # Added to the deciding transaction: the outcome record commits or rolls back with the decision.
    db.add(PolicyDecisionLog(**build_gate_record(
        gate=approval_gate(approval),
        outcome=approval.status,
        action="approval",
        resource=approval.action or "",
        principal=await _label(db, approval.approved_by),
        workspace_id=workspace_id,
        session_id=approval.session_id,
        rule=f"approval rule: {rule}" if rule and "time limit" not in rule else rule,
        reason=approval.decision_note,
        approval_id=approval.id,
        actor_id=approval.approved_by,
        created_at=approval.resolved_at,
    )))


__all__ = ["approval_gate", "record_approval_decided"]
