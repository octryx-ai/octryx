"""Proposed checks kept in the database: made when a signature reaches the Workspace's threshold, edited, approved under
four eyes, rejected with a reason, switched on and off."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CheckProposal
from ...time_utils import utc_now
from ..observability.check_proposal_metrics import count
from .rules import (
    STATE_APPROVED,
    STATE_PROPOSED,
    STATE_REJECTED,
    CheckProposalRefusedError,
    approve_refusal,
    editable_refusal,
    instead_refusal,
    reason_refusal,
)
from .settings import settings, value

STATES = (STATE_PROPOSED, STATE_APPROVED, STATE_REJECTED)
MAX_OCCURRENCES = 20


def evidence(signature: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    found = [item for item in signature.get("occurrences") or [] if isinstance(item, dict)
             and item.get("source") in sources]
    by_source: dict[str, int] = {}
    for item in found:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1
    newest = sorted(found, key=lambda item: str(item.get("at") or ""), reverse=True)[:MAX_OCCURRENCES]
    return {"repeats": len(found), "runs": len({item.get("run_id") for item in found if item.get("run_id")}),
            "sources": by_source, "occurrences": newest}


async def signature_seen(db: AsyncSession, workspace_id: str, config: dict[str, Any] | None,
                         signature: dict[str, Any]) -> CheckProposal | None:
    found = evidence(signature, list(value(config, "sources")))
    existing = (await db.execute(select(CheckProposal).where(
        CheckProposal.workspace_id == workspace_id, CheckProposal.signature_id == str(signature["id"]))
        .order_by(CheckProposal.created_at.desc()).limit(1))).scalar_one_or_none()
    if existing is not None:
        existing.evidence = found
        existing.updated_at = utc_now()
        return existing
    if found["repeats"] < int(value(config, "threshold")):
        return None
    kind = str(signature.get("check_kind") or signature.get("kind_hint") or "")
    proposal = CheckProposal(workspace_id=workspace_id, signature_id=str(signature["id"]), state=STATE_PROPOSED,
                             evidence=found, draft={"kind": kind}, message={}, old_instances={},
                             proof={"state": "not_run"}, severity="warning", enabled=True,
                             author={"kind": "platform", "user_id": None}, edits=[])
    db.add(proposal)
    await db.flush()
    count(workspace_id, kind, STATE_PROPOSED)
    return proposal


def view(proposal: CheckProposal, *, full: bool = True) -> dict[str, Any]:
    found = dict(proposal.evidence or {})
    return {"id": proposal.id, "workspace_id": proposal.workspace_id, "signature_id": proposal.signature_id,
            "state": proposal.state,
            "evidence": found if full else {key: item for key, item in found.items() if key != "occurrences"},
            "draft": dict(proposal.draft or {}), "message": dict(proposal.message or {}),
            "old_instances": dict(proposal.old_instances or {}), "proof": dict(proposal.proof or {}),
            "severity": proposal.severity, "enabled": proposal.enabled, "author": dict(proposal.author or {}),
            "edits": list(proposal.edits or []), "decision": proposal.decision,
            "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
            "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None}


async def _row(db: AsyncSession, workspace_id: str, proposal_id: str) -> CheckProposal:
    found = await db.get(CheckProposal, proposal_id)
    if found is None or found.workspace_id != workspace_id:
        raise CheckProposalRefusedError("not_found", "No such proposed check in this Workspace.", 404)
    return found


async def _saved(db: AsyncSession, proposal: CheckProposal) -> dict[str, Any]:
    proposal.updated_at = utc_now()
    await db.commit()
    await db.refresh(proposal)
    return view(proposal)


async def list_proposals(db: AsyncSession, workspace_id: str, states: set[str] | None = None,
                         limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    query = select(CheckProposal).where(CheckProposal.workspace_id == workspace_id)
    if states:
        query = query.where(CheckProposal.state.in_(sorted(states)))
    if cursor:
        query = query.where(CheckProposal.id < cursor)
    rows = list((await db.execute(query.order_by(CheckProposal.id.desc()).limit(limit + 1))).scalars())
    totals = dict((await db.execute(select(CheckProposal.state, func.count()).where(
        CheckProposal.workspace_id == workspace_id).group_by(CheckProposal.state))).all())
    return {"items": [view(item, full=False) for item in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
            "counts": {state: int(totals.get(state, 0)) for state in STATES}}


async def get(db: AsyncSession, workspace_id: str, proposal_id: str) -> dict[str, Any]:
    return view(await _row(db, workspace_id, proposal_id))


async def edit(db: AsyncSession, workspace_id: str, proposal_id: str, *, user_id: str,
               body: dict[str, Any]) -> dict[str, Any]:
    proposal = await _row(db, workspace_id, proposal_id)
    if refusal := editable_refusal(view(proposal)):
        raise refusal
    changed: list[str] = []
    if isinstance(body.get("message"), dict):
        message = {**dict(proposal.message or {}), **{key: str(text) for key, text in body["message"].items()
                                                     if key in ("what", "why", "instead")}}
        if refusal := instead_refusal(message):
            raise refusal
        proposal.message, changed = message, [*changed, *[f"message.{key}" for key in body["message"]]]
    if isinstance(body.get("draft"), dict):
        proposal.draft = {**dict(proposal.draft or {}), **{key: item for key, item in body["draft"].items()
                                                          if key in ("summary", "rule")}}
        changed += [f"draft.{key}" for key in body["draft"]]
        if "rule" in body["draft"]:
            proposal.proof = {"state": "not_run"}  # a changed rule is proven anew (``proof.prove_due``)
    if body.get("severity") in ("warning", "error"):
        proposal.severity, changed = body["severity"], [*changed, "severity"]
    if changed:
        proposal.edits = [*list(proposal.edits or []), {"by": user_id, "at": utc_now().isoformat(),
                                                        "fields": sorted(set(changed))}]
        count(workspace_id, str(dict(proposal.draft or {}).get("kind") or ""), "edited")
    return await _saved(db, proposal)


async def approve(db: AsyncSession, workspace_id: str, proposal_id: str, *, user_id: str, may_approve: bool,
                  accept_unproven: bool = False, note: str = "") -> dict[str, Any]:
    proposal = await _row(db, workspace_id, proposal_id)
    if refusal := approve_refusal(view(proposal), user_id=user_id, may_approve=may_approve,
                                  accept_unproven=accept_unproven):
        raise refusal
    if not dict(proposal.draft or {}).get("rule") or instead_refusal(dict(proposal.message or {})):
        raise CheckProposalRefusedError("draft_incomplete", "The check is not drafted yet; instead wait for the draft "
                                        "or write its rule and what to do instead.")
    proposal.state = STATE_APPROVED
    proposal.decision = {"state": STATE_APPROVED, "by": user_id, "at": utc_now().isoformat(), "reason": note[:500],
                         "accept_unproven": bool(accept_unproven)}
    count(workspace_id, str(dict(proposal.draft or {}).get("kind") or ""), STATE_APPROVED)
    return await _saved(db, proposal)


async def reject(db: AsyncSession, workspace_id: str, proposal_id: str, *, user_id: str, may_approve: bool,
                 reason: str) -> dict[str, Any]:
    proposal = await _row(db, workspace_id, proposal_id)
    if refusal := editable_refusal(view(proposal)):
        raise refusal
    if not may_approve:
        raise CheckProposalRefusedError("approver_permission_missing", "You may not decide on checks in this "
                                        "Workspace; instead ask the Workspace owner.", 403)
    if refusal := reason_refusal(reason):
        raise refusal
    proposal.state = STATE_REJECTED
    proposal.decision = {"state": STATE_REJECTED, "by": user_id, "at": utc_now().isoformat(), "reason": reason.strip()}
    count(workspace_id, str(dict(proposal.draft or {}).get("kind") or ""), STATE_REJECTED)
    return await _saved(db, proposal)


async def set_enabled(db: AsyncSession, workspace_id: str, proposal_id: str, *, may_approve: bool, value: bool,
                      reason: str, user_id: str = "") -> dict[str, Any]:
    proposal = await _row(db, workspace_id, proposal_id)
    if proposal.state != STATE_APPROVED:
        raise CheckProposalRefusedError("not_approved", "Only an approved check is switched on or off.")
    if not may_approve:
        raise CheckProposalRefusedError("approver_permission_missing", "Ask the Workspace owner to switch this check.",
                                        403)
    if refusal := reason_refusal(reason):
        raise refusal
    proposal.enabled = bool(value)
    proposal.edits = [*list(proposal.edits or []), {"by": user_id or None, "at": utc_now().isoformat(),
                                                    "fields": ["enabled"], "reason": reason.strip()[:500]}]
    return await _saved(db, proposal)


async def workspace_settings(db: AsyncSession, workspace_id: str) -> dict[str, Any]:
    from ...models import Project

    project = await db.get(Project, workspace_id)
    return settings(project.config if project is not None else None)


__all__ = ["approve", "edit", "evidence", "get", "list_proposals", "reject", "set_enabled", "signature_seen",
           "view", "workspace_settings"]
