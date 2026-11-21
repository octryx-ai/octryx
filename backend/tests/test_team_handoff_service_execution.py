"""Execution binding: the allocator and continuation recheck the main link, parent and runtime, the dispatch target and the child checksum."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Session, WorkflowRun
from app.services.workflow_runs.handoff import service
from app.services.workflow_runs.handoff.contract import canonical_hash
from tests.team_handoff_service_support import own_tables  # noqa: F401
from tests.team_handoff_support import action, allocate, counts, rights, setup_case

pytestmark = pytest.mark.asyncio


async def drift_execution_link(db, child, session, cause, sender):
    from app.models import WorkflowRunSession
    link = (await db.execute(select(WorkflowRunSession).where(
        WorkflowRunSession.run_id == child.id, WorkflowRunSession.active.is_(True)))).scalar_one()
    if cause == "missing_main":
        await db.delete(link)
    elif cause == "inactive_main":
        link.active = False
    elif cause == "wrong_role":
        link.role = "reviewer"
    elif cause == "extra_main":
        db.add(WorkflowRunSession(run_id=child.id, session_id=session.id, role="main", runtime="chat", active=True))
    elif cause in {"wrong_main", "parent_session"}:
        other = Session(user_id=sender.id, project_id=session.project_id)
        db.add(other)
        await db.flush()
        if cause == "wrong_main":
            link.session_id = other.id
        else:
            session.parent_session_id = other.id
    elif cause == "runtime_missing":
        child.context = {}
    elif cause == "runtime_changed":
        child.context = {"runtime_target": {"kind": "terminal"}}
    else:
        child.context = {"runtime_target": {"kind": "server", "chosen_by": sender.id}}
    await db.flush()


_EXECUTION_DRIFTS = ["missing_main", "inactive_main", "wrong_role", "extra_main", "wrong_main",
                     "parent_session", "runtime_missing", "runtime_changed", "runtime_author"]


@pytest.mark.parametrize("cause", _EXECUTION_DRIFTS)
async def test_allocator_must_prove_actual_main_link_parent_and_runtime_before_accept(db, cause):
    c = await setup_case(db)
    before = await counts(db)
    async def wrong_factory(**kw):
        result = await allocate(**kw)
        child = await db.get(WorkflowRun, result["child_run_id"])
        session = await db.get(Session, result["receiver_session_id"])
        await drift_execution_link(db, child, session, cause, c.sender)
        return result
    with pytest.raises(HTTPException) as refused:
        await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=wrong_factory)
    assert refused.value.detail["reason"] == "needs_configuration"
    assert c.row.state == "offered" and c.row.child_run_id is None
    assert await counts(db) == before


@pytest.mark.parametrize("cause", _EXECUTION_DRIFTS)
async def test_continuation_rechecks_main_link_parent_and_actual_runtime(db, cause):
    c = await setup_case(db)
    binding = await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=allocate)
    child = await db.get(WorkflowRun, binding["child_run_id"])
    session = await db.get(Session, binding["receiver_session_id"])
    await drift_execution_link(db, child, session, cause, c.sender)
    with pytest.raises(HTTPException) as refused:
        await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights)
    assert refused.value.detail["reason"] == "stale_owner"


async def test_current_runtime_contract_normalizes_valid_receiver_metadata(db):
    from app.services.workflow_runs.runtime_target.target import with_target
    c = await setup_case(db)
    async def normal_factory(**kw):
        result = await allocate(**kw)
        child = await db.get(WorkflowRun, result["child_run_id"])
        child.context = with_target(child.context, kw["runtime_proof"]["runtime_target"], actor_id=kw["actor"].id)
        await db.flush()
        return result
    binding = await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights,
                                         allocator=normal_factory)
    assert await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights) is c.row


async def test_server_target_cannot_hide_session_device_dispatch_target(db):
    from app.services.workflow_runs.runtime_target.target import apply_to_thread
    c = await setup_case(db)
    binding = await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=allocate)
    session = await db.get(Session, binding["receiver_session_id"])
    apply_to_thread(session, {"kind": "device", "device_id": c.q.id, "folder": "/tmp/wrong", "profile": "governed"})
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights)
    assert refused.value.detail["reason"] == "stale_owner"


async def test_device_target_requires_matching_persisted_session_dispatch_binding(db):
    from app.services.workflow_runs.runtime_target.target import apply_to_thread, with_target
    c = await setup_case(db)
    value = action(c.row)
    target = {"kind": "device", "device_id": c.p.id, "folder": "/tmp/controlled", "profile": "governed", "model": ""}
    value["runtime_target"] = target
    async def factory(**kw):
        result = await allocate(**kw)
        child = await db.get(WorkflowRun, result["child_run_id"])
        session = await db.get(Session, result["receiver_session_id"])
        child.context = with_target(child.context, target, actor_id=c.p.id)
        apply_to_thread(session, target)
        await db.flush()
        return result
    binding = await service.accept_handoff(db, c.row.id, c.p, value, rights_evaluator=rights, allocator=factory)
    assert await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights) is c.row
    session = await db.get(Session, binding["receiver_session_id"])
    apply_to_thread(session, {"kind": "server"})
    await db.flush()
    with pytest.raises(HTTPException):
        await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights)


@pytest.mark.parametrize("after_accept", [False, True])
async def test_server_derived_child_checksum_rechecked_before_allocation_and_continuation(db, after_accept):
    from app.models import FlowDefinitionVersion
    c = await setup_case(db)
    version = await db.get(FlowDefinitionVersion, c.row.child_descriptor["version_id"])
    assert c.row.child_descriptor["checksum"] == canonical_hash(version.definition_json)
    binding = None
    if after_accept:
        binding = await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=allocate)
    before = await counts(db)
    version.definition_json = {"execution_kind": "phased", "changed": True}
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        if after_accept:
            await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights)
        else:
            await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=allocate)
    assert refused.value.detail["reason"] == "child_version_changed"
    assert await counts(db) == before
