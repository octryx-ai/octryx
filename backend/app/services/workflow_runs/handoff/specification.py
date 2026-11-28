"""Exact typed specification authority for offers, receivers and child consumers."""
from __future__ import annotations

import copy

from fastapi import HTTPException
from sqlalchemy import select

from ....models import User, WorkflowRun
from ....models.runtime.workflow_handoff import WorkflowHandoff
from ..records import WorkflowRunError
from ..specification.lineage import SpecificationUnavailable, resolve_spec_snapshot
from .contract import refuse

KIND = "spec"


def _claims_spec(value) -> bool:
    return isinstance(value, (dict, list, tuple, str)) and KIND in value


def _declares_spec(row) -> bool:
    contract = row.contract if isinstance(row.contract, dict) else {}
    return _claims_spec(row.envelopes) or _claims_spec(contract.get("artefacts"))


async def has_spec_handoff(db, child) -> bool:
    # A missing or malformed proof never selects a permissive fallback.
    context = dict(child.context or {})
    if any(_claims_spec(context.get(key)) for key in ("handoff_approved_envelopes", "handoff")):
        return True
    row = (await db.execute(select(WorkflowHandoff).where(WorkflowHandoff.child_run_id == child.id)
                            .execution_options(populate_existing=True))).scalar_one_or_none()
    if row is not None and _declares_spec(row):
        return True
    from .lifecycle import child_offer

    historical = await child_offer(db, child)
    return historical is not None and _declares_spec(historical)


def _parent_id(proof) -> str:
    envelope = proof.get("envelope") if isinstance(proof, dict) else None
    record = envelope.get("record") if isinstance(envelope, dict) else None
    if not isinstance(record, dict) or envelope.get("kind") != KIND:
        refuse("needs_configuration", "The typed specification proof is unavailable")
    refs = [record.get(key) for key in ("idea_frame_ref", "research_brief_ref")]
    ids = [ref.get("parent_run_id") if isinstance(ref, dict) else None for ref in refs]
    if not ids[0] or not isinstance(ids[0], str) or ids[0] != ids[1]:
        refuse("needs_configuration", "The specification has no exact parent identity")
    return ids[0]


def require_spec_parent(row) -> None:
    if _declares_spec(row):
        proof = row.envelopes.get(KIND) if isinstance(row.envelopes, dict) else None
        if _parent_id(proof) != row.parent_run_id:
            refuse("needs_configuration", "The specification parent differs from the durable offer")


async def validate_spec_envelopes(db, *, actor, scope, envelopes, parent=None):
    if not isinstance(envelopes, dict):
        refuse("needs_configuration", "The typed artefact envelopes are unavailable")
    if KIND not in envelopes:
        return None
    from .authority import confirmed_envelopes

    proof = envelopes[KIND]
    parent_id = _parent_id(proof)
    if parent is not None and parent.id != parent_id:
        refuse("needs_configuration", "The specification parent differs from the offer")
    actual = await db.get(WorkflowRun, parent_id, populate_existing=True)
    if (actual is None or actual.project_id != scope.get("workspace_id")
            or actual.work_item_id != scope.get("work_item_id") or actual.repository != scope.get("repository")):
        refuse("needs_configuration", "The specification parent scope changed")
    current = await confirmed_envelopes(db, actual, [KIND])
    if current.get(KIND) != proof:
        refuse("needs_configuration", "The current confirmed specification differs from the offer")
    try:
        snapshot = await resolve_spec_snapshot(db, actual, principal=actor, purpose="preview")
    except SpecificationUnavailable as error:
        raise HTTPException(409, {"reason": "needs_configuration",
                                  "message": "The specification source authority could not be verified"}) from error
    if snapshot["envelope"] != proof["envelope"]:
        refuse("needs_configuration", "The immutable specification differs from its approval")
    sources = {ref["source_id"] for ref in snapshot["evidence"]}
    if not sources or sources - set(scope.get("source_ids") or []):
        refuse("needs_configuration", "The specification evidence is outside the approved source scope")
    return snapshot


async def validate_offering_spec(db, parent, *, scope, envelopes):
    # Never a model-selected identity.
    if KIND in envelopes:
        actor = await db.get(User, parent.requested_by, populate_existing=True)
        await validate_spec_envelopes(db, parent=parent, actor=actor, scope=scope, envelopes=envelopes)


async def resolve_accepted_spec(db, child, *, principal) -> dict:
    # Fixed error reasons withhold all source content when any authority is unproved.
    return await _accepted_snapshot(db, child, principal=principal, owner=True)


async def resolve_viewer_spec(db, child, *, viewer) -> dict:
    # The owner's authority is never a grant to the viewer.
    return await _accepted_snapshot(db, child, principal=viewer,
                                    owner=getattr(viewer, "id", None) == child.requested_by)


async def _accepted_snapshot(db, child, *, principal, owner: bool) -> dict:
    from .lifecycle import guard_receiver
    from .service import accepted_binding

    actor_id = principal.id if isinstance(principal, User) else None
    if not actor_id or (owner and actor_id != child.requested_by):
        raise WorkflowRunError("stale_owner", "Only the current specification receiver may consume it.", 403)
    try:
        row = await guard_receiver(db, child)
        if (row is None or row.child_run_id != child.id or row.accepted_by != child.requested_by
                or row.parent_run_id != child.parent_run_id or row.parent_node_id != child.parent_node_id
                or not _declares_spec(row)):
            raise WorkflowRunError("stale_owner", "The accepted specification owner binding is unavailable.", 403)
        context = dict(child.context or {})
        if (context.get("handoff_approved_envelopes") != row.envelopes
                or KIND not in row.envelopes
                or not isinstance(context.get("handoff"), dict)
                or context["handoff"].get(KIND) != row.envelopes[KIND]["envelope"]["record"]):
            raise WorkflowRunError("needs_configuration", "The accepted specification proof changed.", 409)
        parent = await db.get(WorkflowRun, row.parent_run_id, populate_existing=True)
        if parent is None:
            raise WorkflowRunError("needs_configuration", "The accepted specification parent is unavailable.", 409)
        snapshot = await validate_spec_envelopes(
            db, parent=parent, actor=principal, scope=row.contract["scope"], envelopes=row.envelopes)
    except (HTTPException, WorkflowRunError) as error:
        reason = (error.code if isinstance(error, WorkflowRunError) else
                  error.detail.get("reason") if isinstance(error.detail, dict) else None)
        code = "stale_owner" if reason in {"stale_owner", "not_handoff_recipient"} else "needs_configuration"
        raise WorkflowRunError(code, "The accepted specification authority could not be verified.",
                               403 if code == "stale_owner" else 409) from error
    proof = row.envelopes[KIND]
    return {**copy.deepcopy(snapshot), "accepted_binding": copy.deepcopy(accepted_binding(row)),
            "confirmation": {key: proof[key] for key in ("decision_id", "decision_hash", "decided_by")}}
