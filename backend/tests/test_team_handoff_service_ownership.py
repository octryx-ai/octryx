"""Ownership on the real DB: pool acceptors, identity groups bound to a workspace, idempotent repeat offers and owner binding."""

import asyncio
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Session, User, WorkflowRun
from app.models.runtime.workflow_handoff import WorkflowHandoff
from app.services.workflow_runs.handoff import service
from app.services.workflow_runs.handoff.authority import candidates
from app.services.workflow_runs.handoff.contract import canonical_hash
from tests.team_handoff_service_support import own_tables  # noqa: F401
from tests.team_handoff_support import action, allocate, counts, rights, setup_case

pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(not os.environ.get("OCTRYX_HANDOFF_TEST_DATABASE_URL"), reason="root supplies disposable PostgreSQL")
async def test_real_pg_two_pool_acceptors_one_owner_session_and_factory_call():
    engine = create_async_engine(os.environ["OCTRYX_HANDOFF_TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        c = await setup_case(db, pool=True)
        ident, p_id, q_id, value = c.row.id, c.p.id, c.q.id, action(c.row)
        await db.commit()
    allocations = []
    async def counted(**kw):
        allocations.append(kw["actor"].id)
        return await allocate(**kw)
    async def accept(actor_id):
        async with factory() as db:
            actor = await db.get(User, actor_id)
            try:
                result = await service.accept_handoff(db, ident, actor, value, rights_evaluator=rights, allocator=counted)
                await db.commit()
                return result
            except HTTPException:
                await db.rollback()
                return None
    try:
        results = await asyncio.gather(accept(p_id), accept(q_id))
        assert len([r for r in results if r]) == 1 and len(allocations) == 1
        async with factory() as db:
            row = await db.get(WorkflowHandoff, ident)
            assert row.accepted_by in {p_id, q_id} and row.owner_epoch == 1
            assert (await db.execute(select(func.count()).select_from(WorkflowRun).where(
                WorkflowRun.parent_run_id == row.parent_run_id))).scalar_one() == 1
    finally:
        await engine.dispose()


async def test_identity_group_bound_to_workspace_and_revocation_removes_candidate(db):
    from app.models import IdentityGroup, ProjectGroup, UserGroup
    c = await setup_case(db)
    group = IdentityGroup(name=f"handoff-fixture-{c.row.id}", is_active=True)
    db.add(group)
    await db.flush()
    db.add_all([ProjectGroup(project_id=c.row.workspace_id, group_id=group.id),
                UserGroup(user_id=c.p.id, group_id=group.id), UserGroup(user_id=c.q.id, group_id=group.id)])
    await db.flush()
    c.row.target_kind, c.row.target_key = "group", group.id
    c.row.contract = {**c.row.contract, "owner": f"group:{group.id}"}
    c.row.payload_hash = canonical_hash(service.binding_payload(c.row))
    await db.flush()
    assert set(await candidates(db, c.row)) == {c.p.id, c.q.id}
    await db.execute(delete(ProjectGroup).where(ProjectGroup.group_id == group.id))
    assert await candidates(db, c.row) == ()
    before = await counts(db)
    with pytest.raises(HTTPException):
        await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=allocate)
    assert await counts(db) == before


async def test_exact_repeat_offer_idempotent_and_scope_drift_cannot_rebind(db):
    c = await setup_case(db)
    row = await service.offer_handoff(db, c.parent, node_id="offer", contract=c.row.contract,
        child_descriptor={k: c.row.child_descriptor[k] for k in ("workflow_key", "version_id")})
    assert row.id == c.row.id
    assert (await db.execute(select(func.count()).select_from(WorkflowHandoff).where(
        WorkflowHandoff.parent_run_id == c.parent.id))).scalar_one() == 1
    with pytest.raises(HTTPException):
        await service.offer_handoff(db, c.parent, node_id="offer", contract={**c.row.contract, "acceptance": "Changed"},
            child_descriptor={k: c.row.child_descriptor[k] for k in ("workflow_key", "version_id")})


@pytest.mark.parametrize("drift", ["child_owner", "session_owner", "child_repository", "child_version"])
async def test_current_owner_requires_persisted_child_and_session_binding(db, drift):
    c = await setup_case(db)
    binding = await service.accept_handoff(db, c.row.id, c.p, action(c.row), rights_evaluator=rights, allocator=allocate)
    child = await db.get(WorkflowRun, binding["child_run_id"])
    session = await db.get(Session, binding["receiver_session_id"])
    if drift == "child_owner":
        child.requested_by = c.sender.id
    elif drift == "session_owner":
        session.user_id = c.sender.id
    elif drift == "child_repository":
        child.repository = "bitbucket:other/repo"
    else:
        child.flow_definition_version_id = c.parent.flow_definition_version_id
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        await service.require_owner_binding(db, c.row.id, binding, rights_evaluator=rights)
    assert refused.value.detail["reason"] == "stale_owner"
