"""Atomic offers, acceptance and owner lifecycle; connector/runtime I/O is outside this service."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, User, WorkflowRun, WorkflowRunSession
from ....models.runtime.workflow_handoff import WorkflowHandoff, WorkflowHandoffResponse
from ....time_utils import utc_now
from ..records import WorkflowRunError, record_event
from ..runtime_target.target import parse_target, stored_target
from .authority import candidates, confirmed_envelopes, require_candidate
from .contract import canonical_hash, owner_ref, refuse, validate_action, validate_contract
from .rules import (
    WAITING_HANDOFF,
    RightsEvaluator,
    _action_current,
    _cas,
    _descriptor,
    _hash_valid,
    _parent_valid,
    _rights,
    _sources_current,
    _utc,
    binding_payload,
)

Allocator = Callable[..., Awaitable[dict]]


async def offer_handoff(db: AsyncSession, parent: WorkflowRun, *, node_id: str, contract: dict,
                        child_descriptor: dict) -> WorkflowHandoff:
    contract = validate_contract(contract)
    scope = contract["scope"]
    if (scope["workspace_id"] != parent.project_id or scope["work_item_id"] != parent.work_item_id
            or scope["repository"] != parent.repository or parent.current_node_id != node_id
            or type(dict(parent.node_state or {}).get("entry")) is not int
            or not parent.flow_definition_version_id):
        refuse("handoff_scope_mismatch", "The authored scope must match the exact parent binding")
    if not isinstance(child_descriptor, dict) or set(child_descriptor) != {"workflow_key", "version_id"}:
        refuse("needs_configuration", "Only authored child key/version references are accepted")
    child_descriptor = await _descriptor(db, child_descriptor, parent)
    envelopes = await confirmed_envelopes(db, parent, contract["artefacts"])
    from .specification import validate_offering_spec

    await validate_offering_spec(db, parent, scope=scope, envelopes=envelopes)
    entry = parent.node_state["entry"]
    existing = (await db.execute(select(WorkflowHandoff).where(WorkflowHandoff.parent_run_id == parent.id,
        WorkflowHandoff.parent_node_id == node_id, WorkflowHandoff.parent_entry == entry))).scalar_one_or_none()
    if existing:
        _hash_valid(existing)
        if (existing.contract != contract or existing.envelopes != envelopes
                or existing.child_descriptor != child_descriptor):
            refuse("handoff_changed", "An existing offer cannot adopt new content or scope")
        return existing
    if parent.status not in {"running", "waiting"}:
        refuse("stale_parent", "A terminal parent cannot offer a child")
    kind, key = owner_ref(contract["owner"])
    now = utc_now()
    row = WorkflowHandoff(parent_run_id=parent.id, parent_node_id=node_id, parent_entry=entry,
        parent_state_version=parent.state_version, parent_version_id=parent.flow_definition_version_id,
        child_descriptor=child_descriptor, workspace_id=parent.project_id, requested_by=parent.requested_by,
        target_kind=kind, target_key=key, contract=contract, envelopes=envelopes, acceptance=contract["acceptance"],
        detach=contract["detach"], state="offered", state_version=1, owner_epoch=0, round=1, deputy_active=False,
        schema_version="handoff/v1", owner_history=[], issued_at=now,
        expires_at=now + timedelta(seconds=contract["timeout_seconds"]))
    row.payload_hash = canonical_hash(binding_payload(row))
    db.add(row)
    parent.status, parent.waiting_kind = "waiting", WAITING_HANDOFF
    await db.flush()
    record_event(db, parent, "handoff.offered", node_id=node_id, detail={"handoff_id": row.id,
        "payload_hash": row.payload_hash, "round": row.round, "child_version_id": child_descriptor["version_id"]})
    return row


async def lock_handoff(db: AsyncSession, handoff_id: str) -> tuple[WorkflowRun, WorkflowHandoff]:
    identity = (await db.execute(select(WorkflowHandoff.parent_run_id, WorkflowHandoff.child_run_id)
                                .where(WorkflowHandoff.id == handoff_id))).first()
    if identity is None:
        refuse("not_found", "Handoff not found", 404)
    from ..records import WorkflowRunError
    from .lifecycle import lock_parent_chain

    # Ancestors, parent, child, then the offer row: the receiver and offer paths share this order to avoid a deadlock.
    try:
        await lock_parent_chain(db, identity.parent_run_id)
    except WorkflowRunError as error:
        refuse(error.code, str(error), error.status_code)
    parent = (await db.execute(select(WorkflowRun).where(WorkflowRun.id == identity.parent_run_id)
        .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if parent is None:
        refuse("not_found", "Handoff not found", 404)
    if identity.child_run_id:
        await db.execute(select(WorkflowRun).where(WorkflowRun.id == identity.child_run_id)
                         .with_for_update().execution_options(populate_existing=True))
    row = (await db.execute(select(WorkflowHandoff).where(WorkflowHandoff.id == handoff_id).with_for_update()
        .execution_options(populate_existing=True))).scalar_one()
    if row.parent_run_id != identity.parent_run_id or row.child_run_id != identity.child_run_id:
        refuse("handoff_changed", "The child changed while claiming the offer")
    return parent, row


async def preview_handoff(db: AsyncSession, handoff_id: str, actor: User, *,
                          rights_evaluator: RightsEvaluator | None) -> dict:
    parent, row = await lock_handoff(db, handoff_id)
    if actor.id not in await candidates(db, row) and not (row.state == "accepted" and row.accepted_by == actor.id):
        refuse("not_found", "Handoff not found", 404)
    _hash_valid(row)
    await _sources_current(db, parent, row)
    await _rights(db, row, actor, None, rights_evaluator)
    return {"id": row.id, "state": row.state, "payload_hash": row.payload_hash, "round": row.round,
        "state_version": row.state_version, "acceptance": row.acceptance, "scope": row.contract["scope"],
        "artefacts": row.envelopes, "expires_at": _utc(row.expires_at).isoformat(),
        "child_descriptor": row.child_descriptor}


async def _execution_link(db: AsyncSession, child: WorkflowRun, session: Session, runtime: dict,
                           actor_id: str, *, reason: str, status: int) -> None:
    from ..octryx.continuation_marker import _device_target

    session = (await db.execute(select(Session).where(Session.id == session.id).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none()
    links = list((await db.execute(select(WorkflowRunSession).where(
        WorkflowRunSession.run_id == child.id, WorkflowRunSession.role == "main",
        WorkflowRunSession.active.is_(True)).with_for_update()
        .execution_options(populate_existing=True))).scalars())
    target = stored_target(child)
    try:
        expected, thread_target = parse_target(runtime), _device_target(session)
        matches = target is not None and parse_target(target) == expected
        if expected and expected["kind"] == "device":
            matches = matches and parse_target(thread_target) == expected
        else:
            matches = matches and thread_target is None
    except WorkflowRunError:
        matches = False
    if (session is None or session.user_id != actor_id or session.project_id != child.project_id
            or len(links) != 1 or links[0].session_id != session.id or session.parent_session_id is not None
            or not matches or (target is not None and target.get("chosen_by", actor_id) != actor_id)):
        refuse(reason, "The active child main Session or accepted runtime binding is not proved", status)


async def accept_handoff(db: AsyncSession, handoff_id: str, actor: User, action: dict, *,
                         rights_evaluator: RightsEvaluator | None, allocator: Allocator | None) -> dict:
    action = validate_action(action)
    if action["action"] != "accept":
        refuse("invalid_action", "Acceptance is required", 422)
    parent, row = await lock_handoff(db, handoff_id)
    await require_candidate(db, row, actor.id, lock=True)
    _action_current(row, action)
    _parent_valid(parent, row)
    await _sources_current(db, parent, row)
    proof = await _rights(db, row, actor, action["runtime_target"], rights_evaluator)
    if allocator is None:
        refuse("needs_configuration", "The dormant child factory is not configured")
    # The factory must make only DB rows. A savepoint prevents a refused factory from leaving allocations.
    async with db.begin_nested():
        allocated = await allocator(db=db, parent=parent, handoff=row, actor=actor, runtime_proof=proof)
        child = await db.get(WorkflowRun, allocated.get("child_run_id")) if isinstance(allocated, dict) else None
        session = await db.get(Session, allocated.get("receiver_session_id")) if isinstance(allocated, dict) else None
        if (not child or not session or child.requested_by != actor.id or session.user_id != actor.id
                or child.flow_definition_version_id != row.child_descriptor["version_id"]
                or child.parent_run_id != parent.id or child.parent_node_id != row.parent_node_id
                or child.workflow_key != row.child_descriptor["workflow_key"]
                or child.work_item_id != row.contract["scope"]["work_item_id"]
                or child.repository != row.contract["scope"]["repository"]
                or child.project_id != row.workspace_id or session.project_id != row.workspace_id
                or session.parent_session_id is not None):
            refuse("needs_configuration", "The factory did not create the exact receiver-owned child and Session")
        await _execution_link(db, child, session, proof["runtime_target"], actor.id,
                              reason="needs_configuration", status=409)
        await _cas(db, row, state="accepted", child_run_id=child.id, receiver_session_id=session.id,
            accepted_by=actor.id, accepted_at=utc_now(), owner_epoch=row.owner_epoch + 1,
            runtime_snapshot=proof["runtime_target"])
    record_event(db, parent, "handoff.accepted", node_id=row.parent_node_id, actor_id=actor.id,
        detail={"handoff_id": row.id, "owner_epoch": row.owner_epoch, "child_run_id": row.child_run_id,
                "receiver_session_id": row.receiver_session_id, "payload_hash": row.payload_hash})
    return accepted_binding(row)


def accepted_binding(row: WorkflowHandoff) -> dict:
    # Post-commit continuation must claim this epoch idempotently before any engine I/O.
    return {"handoff_id": row.id, "child_run_id": row.child_run_id, "receiver_session_id": row.receiver_session_id,
        "actor_id": row.accepted_by, "owner_epoch": row.owner_epoch, "payload_hash": row.payload_hash,
        "runtime_target": row.runtime_snapshot}


async def decline_handoff(db: AsyncSession, handoff_id: str, actor: User, action: dict) -> WorkflowHandoff:
    action = validate_action(action)
    if action["action"] != "decline":
        refuse("invalid_action", "A personal decline is required", 422)
    parent, row = await lock_handoff(db, handoff_id)
    await require_candidate(db, row, actor.id, lock=True)
    _action_current(row, action)
    _parent_valid(parent, row)
    db.add(WorkflowHandoffResponse(handoff_id=row.id, round=row.round, user_id=actor.id, reason=action["reason"]))
    await db.flush()
    remaining = await candidates(db, row)
    await _cas(db, row, **({"state": "rejected"} if not remaining else {}))
    record_event(db, parent, "handoff.personal_declined", node_id=row.parent_node_id, actor_id=actor.id,
        detail={"handoff_id": row.id, "round": row.round, "remaining_count": len(remaining)})
    if not remaining:
        record_event(db, parent, "handoff.rejected", node_id=row.parent_node_id, detail={"handoff_id": row.id})
    return row


async def require_owner_binding(db: AsyncSession, handoff_id: str, binding: dict, *,
                                 rights_evaluator: RightsEvaluator | None) -> WorkflowHandoff:
    parent, row = await lock_handoff(db, handoff_id)
    _hash_valid(row)
    if row.state != "accepted" or binding != accepted_binding(row):
        refuse("stale_owner", "The receiver execution binding is no longer current", 403)
    await require_candidate(db, row, row.accepted_by, lock=True)
    await _sources_current(db, parent, row)
    actor = await db.get(User, row.accepted_by, populate_existing=True)
    child = await db.get(WorkflowRun, row.child_run_id, populate_existing=True)
    session = await db.get(Session, row.receiver_session_id, populate_existing=True)
    if (not child or not session or child.requested_by != row.accepted_by or session.user_id != row.accepted_by
            or child.flow_definition_version_id != row.child_descriptor["version_id"]
            or child.project_id != row.workspace_id or session.project_id != row.workspace_id
            or child.parent_run_id != parent.id or child.parent_node_id != row.parent_node_id
            or child.repository != row.contract["scope"]["repository"]
            or child.work_item_id != row.contract["scope"]["work_item_id"]):
        refuse("stale_owner", "The persisted child or receiver Session changed", 403)
    await _execution_link(db, child, session, row.runtime_snapshot, row.accepted_by,
                          reason="stale_owner", status=403)
    await _rights(db, row, actor, row.runtime_snapshot, rights_evaluator)
    return row
