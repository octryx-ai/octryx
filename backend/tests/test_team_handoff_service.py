"""Real DB paths: dormant offers and zero-effect refusal before allocation."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, update

from app.models import Session, User, WorkflowRun, WorkflowRunDecision
from app.models.security.user import UserProject
from app.services.workflow_runs.handoff import owner_lifecycle, service
from app.services.workflow_runs.handoff.authority import candidates, confirmed_envelopes
from app.services.workflow_runs.handoff.contract import canonical_hash
from app.services.workflow_runs.phase_outputs import output_hash
from app.time_utils import utc_now
from tests.team_handoff_service_support import own_tables  # noqa: F401
from tests.team_handoff_support import action, allocate, counts, rights, setup_case

pytestmark = pytest.mark.asyncio


async def test_offer_is_dormant_and_preview_never_leaks_sender_transcript(db):
    c = await setup_case(db)
    before = await counts(db)
    assert c.row.child_run_id is None and c.row.receiver_session_id is None
    preview = await service.preview_handoff(db, c.row.id, c.p, rights_evaluator=rights)
    assert "SENDER_ONLY_CANARY" not in str(preview)
    assert preview["artefacts"]["definition_of_ready"]["decision_hash"] == c.decision.payload_hash
    for actor in (c.q, c.sender, c.outsider):
        with pytest.raises(HTTPException) as denied:
            await service.preview_handoff(db, c.row.id, actor, rights_evaluator=rights)
        assert denied.value.status_code == 404
    assert await counts(db) == before


async def test_accept_allocates_exact_receiver_and_replay_never_allocates(db):
    c = await setup_case(db)
    before, original = await counts(db), action(c.row)
    binding = await service.accept_handoff(db, c.row.id, c.p, original, rights_evaluator=rights, allocator=allocate)
    assert binding["actor_id"] == c.p.id and binding["owner_epoch"] == 1
    assert await counts(db) == tuple(n + 1 for n in before)
    await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights)
    child = await db.get(WorkflowRun, binding["child_run_id"])
    assert "sender_transcript" not in child.context
    with pytest.raises(HTTPException):
        await service.accept_handoff(db, c.row.id, c.p, original, rights_evaluator=rights, allocator=allocate)
    assert await counts(db) == tuple(n + 1 for n in before)


@pytest.mark.parametrize("cause", ["outsider", "admin", "missing_rights", "missing_factory", "wrong_proof",
    "wrong_runtime", "hash", "round", "version", "expiry", "parent_node", "parent_entry", "parent_version",
    "parent_scope", "source_body", "new_changed_decision", "membership", "inactive", "service_account"])
async def test_stale_or_unproved_accept_has_zero_allocations(db, cause):
    c = await setup_case(db)
    before = await counts(db)
    value, actor, evaluator, factory = action(c.row), c.p, rights, allocate
    if cause in {"outsider", "admin"}:
        actor = c.outsider if cause == "outsider" else c.sender
    elif cause == "missing_rights":
        evaluator = None
    elif cause == "missing_factory":
        factory = None
    elif cause in {"wrong_proof", "wrong_runtime"}:
        async def evaluator(**kw):
            proof = await rights(**kw)
            proof["actor_id" if cause == "wrong_proof" else "runtime_target"] = c.sender.id
            return proof
    elif cause in {"hash", "round", "version"}:
        key = {"hash": "payload_hash", "round": "round", "version": "expected_state_version"}[cause]
        value[key] = output_hash({}) if cause == "hash" else value[key] + 1
    elif cause == "expiry":
        c.row.expires_at = utc_now() - timedelta(seconds=1)
        c.row.payload_hash = canonical_hash(service.binding_payload(c.row))
        value = action(c.row)
    elif cause.startswith("parent_"):
        if cause == "parent_node":
            c.parent.current_node_id = "elsewhere"
        elif cause == "parent_entry":
            c.parent.node_state = {"entry": 5}
        elif cause == "parent_version":
            c.parent.flow_definition_version_id = c.row.child_descriptor["version_id"]
        else:
            c.parent.repository = "bitbucket:other/repo"
    elif cause == "source_body":
        c.parent.context = {**c.parent.context, "outputs": {"definition_of_ready": {
            **c.parent.context["outputs"]["definition_of_ready"], "record": {"summary": "changed"}}}}
    elif cause == "new_changed_decision":
        db.add(WorkflowRunDecision(run_id=c.parent.id, kind="confirmation", subject="advance", action="changed",
            payload=c.decision.payload, payload_hash=c.decision.payload_hash, decided_by=c.sender.id,
            created_at=utc_now() + timedelta(seconds=1)))
    elif cause == "membership":
        await db.execute(delete(UserProject).where(UserProject.user_id == actor.id))
    else:
        await db.execute(update(User).where(User.id == actor.id).values(
            **({"is_active": False} if cause == "inactive" else {"account_type": "service"})))
    await db.flush()
    called = []
    async def tracked(**kw):
        called.append(True)
        return await factory(**kw)
    with pytest.raises(HTTPException):
        await service.accept_handoff(db, c.row.id, actor, value, rights_evaluator=evaluator,
                                     allocator=tracked if factory else None)
    assert not called and await counts(db) == before and c.row.state == "offered"


async def test_personal_decline_leaves_other_pool_candidate_and_all_declines_reject(db):
    c = await setup_case(db, pool=True)
    await service.decline_handoff(db, c.row.id, c.p, action(c.row, "decline"))
    assert c.row.state == "offered" and await candidates(db, c.row) == (c.q.id,)
    with pytest.raises(HTTPException):
        await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=allocate)
    await service.decline_handoff(db, c.row.id, c.q, action(c.row, "decline"))
    assert c.row.state == "rejected" and c.row.child_run_id is None


async def test_timeout_deputy_new_hash_and_old_card_never_allocates(db):
    c = await setup_case(db, deputy="role:doc_owner")
    c.row.expires_at = utc_now() - timedelta(seconds=1)
    c.row.payload_hash = canonical_hash(service.binding_payload(c.row))
    old = action(c.row)
    await owner_lifecycle.expire_handoff(db, c.row.id)
    assert c.row.state == "offered" and c.row.round == 2 and c.row.deputy_active
    assert c.row.payload_hash != old["payload_hash"] and c.row.child_run_id is None
    with pytest.raises(HTTPException):
        await service.accept_handoff(db, c.row.id, c.p, old, rights_evaluator=rights, allocator=allocate)
    await service.accept_handoff(db, c.row.id, c.q, action(c.row), rights_evaluator=rights, allocator=allocate)


@pytest.mark.parametrize("detached", [False, True])
async def test_parent_abort_revokes_only_non_detached_child(db, detached):
    c = await setup_case(db, detach=detached)
    binding = await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=allocate)
    await owner_lifecycle.parent_aborted(db, c.row.id)
    child = await db.get(WorkflowRun, binding["child_run_id"])
    if detached:
        assert c.row.state == "accepted" and child.status == "waiting"
    else:
        assert c.row.state == "stopped" and child.status == "stopped"
        with pytest.raises(HTTPException):
            await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights)


async def test_owner_loss_revokes_epoch_and_child_completion_never_rebinds_parent(db):
    c = await setup_case(db)
    binding = await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=allocate)
    child = await db.get(WorkflowRun, binding["child_run_id"])
    child.status, child.outcome = "completed", "done"
    await db.flush()
    result = await owner_lifecycle.child_finished(db, c.row.id, owner_epoch=1)
    assert result["parent_run_id"] == c.parent.id and result["outcome"] == "done"
    assert c.parent.status == "waiting"
    assert await owner_lifecycle.child_finished(db, c.row.id, owner_epoch=1) == result
    with pytest.raises(HTTPException):
        await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights)
    other = await setup_case(db)
    binding = await service.accept_handoff(db, other.row.id, other.p, action(other.row), rights_evaluator=rights,
                                         allocator=allocate)
    await owner_lifecycle.revoke_owner(db, other.row.id, reason="membership revoked")
    assert other.row.state == "owner_lost" and other.row.owner_epoch == 2
    with pytest.raises(HTTPException):
        await service.require_owner_binding(db, other.row.id, binding, rights_evaluator=rights)


async def test_bad_factory_ownership_rolls_back_allocations(db):
    c = await setup_case(db)
    before = await counts(db)
    async def wrong_factory(**kw):
        result = await allocate(**kw)
        session = await db.get(Session, result["receiver_session_id"])
        session.user_id = c.sender.id
        await db.flush()
        return result
    with pytest.raises(HTTPException):
        await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=wrong_factory)
    assert await counts(db) == before


async def test_same_named_draft_is_not_a_confirmed_body(db):
    c = await setup_case(db)
    c.decision.payload = {"shows": "definition_of_ready", "output": {
        "version": 1, "hash": c.row.envelopes["definition_of_ready"]["envelope"]["hash"], "summary": "draft"}}
    c.decision.payload_hash = output_hash(c.decision.payload)
    await db.flush()
    with pytest.raises(HTTPException):
        await confirmed_envelopes(db, c.parent, ["definition_of_ready"])
