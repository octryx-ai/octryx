"""Observability → Decisions: the timeline of every non-allow outcome of every gate (O2).

Reads ``policy_decision_log`` (bounded window, server paging, filters by outcome, gate, Workspace, policy, run,
approval) and ``policy_decision_counters`` (allows, counted per hour). A record of an older revision without a
``gate`` is attributed by its point (content → content routing, device dispatch → device job, else Cedar).

``what`` and ``rule`` are served in words by the approval formatter (``approval/presentation``), with the stored
codes next to them as ``what_code``/``rule_code``: raw codes such as "Approve tool execution for run_cli_command"
and "execution_gate: needs_configuration" would disagree with an approval card that says "Run a command on the
Octryx server". An approval's records take the approval card's own title and subtitle, so both pages say the same.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.approval.decision_texts import decision_rule_text, decision_what

from ...models import (
    ChangePreview,
    PolicyDecisionCounter,
    PolicyDecisionLog,
    Project,
    Session,
    TurnTraceSummary,
    User,
)
from ...time_utils import ensure_utc, utc_now
from ..approval.presentation import approval_texts
from .recorder import GATE_CEDAR, GATE_CONTENT_ROUTING, GATE_DEVICE_JOB, GATES

WINDOW_HOURS = (24, 168, 720)
DEFAULT_WINDOW_HOURS = 168
MAX_PAGE_SIZE = 100
# What the outcome filter offers; Cedar comparison outcomes (mismatch, custom_policy, error, dropped) are listed
# under "All" and in Settings → Governance → Policies.
OUTCOMES = ("denied", "needs_approval", "approved", "rejected", "expired", "remedied", "reported",
            "needs_clarification", "needs_configuration", "cancelled")


def gate_expression():
    return func.coalesce(
        PolicyDecisionLog.gate,
        case(
            (PolicyDecisionLog.obligation.is_not(None), GATE_CONTENT_ROUTING),
            (PolicyDecisionLog.point == "device_dispatch", GATE_DEVICE_JOB),
            else_=GATE_CEDAR,
        ),
    )


def _iso(value: datetime | None) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def _base(since: datetime):
    gate = gate_expression().label("gate_name")
    return (
        select(PolicyDecisionLog, gate, Session.project_id.label("session_project_id"))
        .outerjoin(Session, Session.id == PolicyDecisionLog.session_id)
        .where(PolicyDecisionLog.created_at >= since)
    )


async def list_decisions(
    db: AsyncSession,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    outcome: str | None = None,
    gate: str | None = None,
    workspace_id: str | None = None,
    policy_id: str | None = None,
    run_key: str | None = None,
    approval_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    window_hours = window_hours if window_hours in WINDOW_HOURS else DEFAULT_WINDOW_HOURS
    page, page_size = max(1, page), max(1, min(MAX_PAGE_SIZE, page_size))
    since = utc_now() - timedelta(hours=window_hours)
    statement = _base(since)
    if outcome:
        statement = statement.where(PolicyDecisionLog.outcome == outcome)
    if gate in GATES:
        statement = statement.where(gate_expression() == gate)
    if workspace_id:
        statement = statement.where(or_(PolicyDecisionLog.workspace_id == workspace_id,
                                        Session.project_id == workspace_id))
    if run_key:
        statement = statement.where(PolicyDecisionLog.run_key == run_key)
    if approval_id:
        statement = statement.where(PolicyDecisionLog.approval_id == approval_id)
    ordered = statement.order_by(PolicyDecisionLog.created_at.desc(), PolicyDecisionLog.id.desc())
    if policy_id:
        # JSON containment differs per dialect; the window and the log's retention bound this set.
        matching = [row for row in (await db.execute(ordered)).all() if policy_id in (row[0].determining or [])]
        total, rows = len(matching), matching[(page - 1) * page_size:page * page_size]
    else:
        total = int((await db.execute(select(func.count()).select_from(statement.subquery()))).scalar() or 0)
        rows = (await db.execute(ordered.limit(page_size).offset((page - 1) * page_size))).all()
    labels = await _labels(db, rows)
    previews = await _approval_previews(db, rows)
    return {
        "window_hours": window_hours,
        "since": _iso(since),
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [_serialize(row, labels, previews) for row in rows],
    }


async def _labels(db: AsyncSession, rows: list[Any]) -> dict[str, str]:
    """Usernames for principals/actors that are user ids, and Workspace names."""
    user_ids = {value for row in rows for value in (row[0].principal, row[0].actor_id) if value}
    workspace_ids = {value for row in rows for value in (row[0].workspace_id, row.session_project_id) if value}
    labels: dict[str, str] = {}
    if user_ids:
        labels.update({user_id: name for user_id, name in (await db.execute(
            select(User.id, User.username).where(User.id.in_(user_ids)))).all()})
    if workspace_ids:
        labels.update({f"ws:{project_id}": name for project_id, name in (await db.execute(
            select(Project.id, Project.name).where(Project.id.in_(workspace_ids)))).all()})
    return labels


async def _approval_previews(db: AsyncSession, rows: list[Any]) -> dict[str, dict[str, Any]]:
    """The newest stored change preview of each approval the rows belong to (one query for the page)."""
    from ..change_preview.service import serialize_change_preview

    approval_ids = {row[0].approval_id for row in rows if row[0].approval_id}
    if not approval_ids:
        return {}
    previews: dict[str, dict[str, Any]] = {}
    for preview in (await db.execute(select(ChangePreview).where(ChangePreview.approval_id.in_(approval_ids))
                                     .order_by(ChangePreview.created_at.desc()))).scalars():
        payload = (serialize_change_preview(preview) or {}).get("preview")
        if preview.approval_id not in previews and isinstance(payload, dict):
            previews[preview.approval_id] = payload
    return previews


def _texts(record: PolicyDecisionLog, previews: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """``what``/``subtitle``/``rule`` in words and the stored codes. An approval's records read like its card; the
    request record (no rule of its own) names the approval's reason, a decision keeps its approval rule."""
    stored_rule = record.rule or (", ".join(record.determining or []) or None)
    preview = previews.get(record.approval_id) if record.approval_id else None
    if record.approval_id and record.action == "approval":
        texts = approval_texts(preview, record.resource or "")
        code = str((preview or {}).get("rule") or "") or None
        return {"what": texts["title"], "subtitle": texts["subtitle"] or None,
                "rule": decision_rule_text(record.rule) if record.rule else (texts["subtitle"] or None),
                "rule_code": record.rule or code}
    return {"what": decision_what(record.resource), "subtitle": None,
            "rule": decision_rule_text(stored_rule) if stored_rule else None, "rule_code": stored_rule}


def _serialize(row: Any, labels: dict[str, str], previews: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    record: PolicyDecisionLog = row[0]
    workspace_id = record.workspace_id or row.session_project_id
    texts = _texts(record, previews or {})
    return {
        "id": record.id,
        "time": _iso(record.created_at),
        "outcome": record.outcome,
        "gate": row.gate_name,
        "action": record.action,
        "what": texts["what"],
        "what_code": record.resource,
        "subtitle": texts["subtitle"],
        "who": labels.get(record.principal, record.principal),
        "decided_by": labels.get(record.actor_id, record.actor_id) if record.actor_id else None,
        "workspace_id": workspace_id,
        "workspace_name": labels.get(f"ws:{workspace_id}") if workspace_id else None,
        "rule": texts["rule"],
        "rule_code": texts["rule_code"],
        "reason": record.reason or record.legacy_reason,
        "mode": record.mode,
        "session_id": record.session_id,
        "run_key": record.run_key,
        "approval_id": record.approval_id,
        "determining_policies": list(record.determining or []),
        "content": record.content,
        "obligation": record.obligation,
        "legacy": {"decision": record.legacy_decision, "reason": record.legacy_reason},
    }


async def get_decision(db: AsyncSession, decision_id: str) -> dict[str, Any] | None:
    row = (await db.execute(
        select(PolicyDecisionLog, gate_expression().label("gate_name"), Session.project_id.label("session_project_id"))
        .outerjoin(Session, Session.id == PolicyDecisionLog.session_id)
        .where(PolicyDecisionLog.id == decision_id)
    )).first()
    if row is None:
        return None
    related = []
    if row[0].approval_id:
        related = (await db.execute(
            select(PolicyDecisionLog, gate_expression().label("gate_name"),
                   Session.project_id.label("session_project_id"))
            .outerjoin(Session, Session.id == PolicyDecisionLog.session_id)
            .where(PolicyDecisionLog.approval_id == row[0].approval_id)
            .order_by(PolicyDecisionLog.created_at)
        )).all()
    labels = await _labels(db, [row, *related])
    previews = await _approval_previews(db, [row, *related])
    run_exists = bool(row[0].run_key) and (await db.execute(
        select(TurnTraceSummary.trace_id).where(TurnTraceSummary.run_key == row[0].run_key).limit(1)
    )).first() is not None
    return {
        **_serialize(row, labels, previews),
        "run_exists": run_exists,
        "lifecycle": [_serialize(item, labels, previews) for item in related],
    }


async def decisions_today(db: AsyncSession) -> dict[str, Any]:
    """Today's (UTC) decisions by outcome and the allows counted today."""
    start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    by_outcome = {
        outcome: int(count)
        for outcome, count in (await db.execute(
            select(PolicyDecisionLog.outcome, func.count()).where(PolicyDecisionLog.created_at >= start)
            .group_by(PolicyDecisionLog.outcome)
        )).all()
    }
    allowed = int((await db.execute(
        select(func.coalesce(func.sum(PolicyDecisionCounter.count), 0)).where(PolicyDecisionCounter.hour >= start)
    )).scalar() or 0)
    return {"since": _iso(start), "by_outcome": by_outcome, "total": sum(by_outcome.values()), "allowed": allowed}


async def policy_denial_counts(db: AsyncSession, *, days: int = 7) -> dict[str, int]:
    """Denied (or would-deny) decisions per determining policy in the last ``days`` (Settings → Policies)."""
    since = utc_now() - timedelta(days=days)
    counts: dict[str, int] = {}
    for (determining,) in (await db.execute(
        select(PolicyDecisionLog.determining).where(
            PolicyDecisionLog.created_at >= since, PolicyDecisionLog.decision == "deny")
    )).all():
        for policy_id in determining or []:
            counts[policy_id] = counts.get(policy_id, 0) + 1
    return counts


__all__ = [
    "DEFAULT_WINDOW_HOURS",
    "OUTCOMES",
    "WINDOW_HOURS",
    "decisions_today",
    "gate_expression",
    "get_decision",
    "list_decisions",
    "policy_denial_counts",
]
