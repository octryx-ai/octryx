from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import aliased, joinedload, selectinload

from app.db import core as db_core
from app.models import AuditLog, Message, Session, SessionAccess, User
from app.models.agent.approval import Approval
from app.services.data_access import (
    Viewer,
    ViewerNotSetError,
    as_viewer,
    current_viewer,
    platform_maintenance,
    set_viewer,
)
from app.services.data_access import viewer as viewer_module
from app.services.data_access.viewer import AUDIT_ACTION, PlatformMaintenanceAuditError
from app.services.project.private_workspace import ensure_private_workspace
from tests.devices.device_support import user_named


async def _private_session(db, owner: User, title: str) -> Session:
    workspace = await ensure_private_workspace(db, owner)
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=workspace.id, origin="chat")
    db.add(session)
    await db.flush()
    db.add(Message(session_id=session.id, role="user", content=f"{title} message"))
    db.add(Approval(session_id=session.id, requested_by=owner.id, action="tool:shell", status="pending",
                    workspace_id=workspace.id, reason=title))
    await db.commit()
    return session


@pytest.fixture
async def two_owners(db):
    owner = await user_named(db, f"filter-owner-{uuid.uuid4().hex[:6]}")
    other = await user_named(db, f"filter-other-{uuid.uuid4().hex[:6]}")
    mine = await _private_session(db, owner, "owner-private")
    theirs = await _private_session(db, other, "other-private")
    db.expunge_all()
    return owner, other, mine.id, theirs.id


async def test_a_viewer_lists_and_counts_only_rows_outside_foreign_private_workspaces(db, two_owners):
    owner, _other, mine, theirs = two_owners
    with as_viewer(owner.id):
        ids = set((await db.execute(select(Session.id))).scalars())
        assert mine in ids and theirs not in ids
        everything = (await db.execute(select(func.count()).select_from(Session))).scalar_one()
    async with platform_maintenance("test: count every session"):
        assert (await db.execute(select(func.count()).select_from(Session))).scalar_one() == everything + 1


async def test_relationship_eager_lazy_and_aliased_loads_are_filtered(db, two_owners):
    owner, _other, mine, theirs = two_owners
    with as_viewer(owner.id):
        for option in (joinedload(Approval.session), selectinload(Approval.session)):
            db.expunge_all()
            approvals = (await db.execute(select(Approval).options(option))).scalars().unique().all()
            assert theirs not in {approval.session_id for approval in approvals}
        session_alias = aliased(Session)
        joined = (await db.execute(select(func.count()).select_from(Approval).join(
            session_alias, session_alias.id == Approval.session_id).where(session_alias.id == theirs))).scalar_one()
        assert joined == 0
        db.expunge_all()
        own_approval = (await db.execute(select(Approval).where(Approval.session_id == mine))).scalar_one()
        assert (await db.run_sync(lambda _sync: own_approval.session)).id == mine


async def test_get_by_id_of_a_foreign_private_row_finds_nothing_in_a_fresh_session(db, two_owners):
    owner, _other, _mine, theirs = two_owners
    with as_viewer(owner.id):
        assert await db.get(Session, theirs) is None


async def test_an_anonymous_viewer_sees_no_private_workspace(db, two_owners):
    _owner, _other, mine, theirs = two_owners
    with as_viewer(None):
        ids = set((await db.execute(select(Session.id))).scalars())
    assert not ids & {mine, theirs}


async def test_an_owner_shared_session_is_visible_to_its_grantee(db, two_owners):
    owner, other, _mine, theirs = two_owners
    db.add(SessionAccess(session_id=theirs, user_id=owner.id, access_scope="read", granted_by=other.id))
    await db.commit()
    with as_viewer(owner.id):
        assert await db.get(Session, theirs) is not None
        assert (await db.execute(select(Approval).where(Approval.session_id == theirs))).scalar_one()


async def test_reads_without_a_viewer_fail_closed_for_workspace_bound_models_only(db, two_owners):
    set_viewer(None)
    with pytest.raises(ViewerNotSetError, match="sessions"):
        await db.execute(select(Session))
    with pytest.raises(ViewerNotSetError, match="approvals"):
        await db.execute(select(func.count()).select_from(Approval))
    assert (await db.execute(select(func.count()).select_from(User))).scalar_one() > 0


@pytest.fixture
def audit_in_test_session(db, monkeypatch):
    class _Shared:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_exc):
            return None

    monkeypatch.setattr(db_core, "async_session_factory", _Shared)


async def test_platform_maintenance_reads_everything_after_its_audit_row_is_committed(
        db, two_owners, audit_in_test_session, monkeypatch):
    _owner, _other, _mine, theirs = two_owners
    reason = f"test: maintenance {uuid.uuid4().hex[:6]}"
    seen_while_auditing = []
    write_audit = viewer_module._audit

    async def audit(state, actor):
        seen_while_auditing.append(current_viewer())
        await write_audit(state, actor)

    monkeypatch.setattr(viewer_module, "_audit", audit)
    with as_viewer(_owner.id):
        async with platform_maintenance(reason):
            assert current_viewer().caller.endswith(
                "test_platform_maintenance_reads_everything_after_its_audit_row_is_committed")
            assert await db.get(Session, theirs) is not None
        assert await db.get(Session, theirs) is None
    assert seen_while_auditing == [Viewer(_owner.id)]
    row = (await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION,
                                                   AuditLog.resource_id == reason))).scalar_one()
    assert (row.user_id, row.details["reason"]) == (_owner.id, reason)


async def test_platform_maintenance_is_refused_when_its_audit_row_cannot_be_written(db, two_owners, monkeypatch):
    async def failing(_state, _actor):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(viewer_module, "_audit", failing)
    with as_viewer(two_owners[0].id):
        with pytest.raises(PlatformMaintenanceAuditError):
            async with platform_maintenance("test: refused"):
                raise AssertionError("never entered")
        assert current_viewer() == Viewer(two_owners[0].id)


async def test_a_binding_is_visible_only_when_both_its_workspaces_are(db, two_owners):
    from app.models import KnowledgeWorkspaceBinding
    from tests.knowledge_evidence_seed_support import seed_workspace

    owner, other, _mine, _theirs = two_owners
    shared = await seed_workspace(db)
    foreign = (await ensure_private_workspace(db, other)).id
    reads_foreign = KnowledgeWorkspaceBinding(reader_project_id=shared, source_project_id=foreign)
    read_by_foreign = KnowledgeWorkspaceBinding(reader_project_id=foreign, source_project_id=shared)
    db.add_all([reads_foreign, read_by_foreign])
    await db.commit()
    both = {reads_foreign.id, read_by_foreign.id}
    db.expunge_all()

    async def visible() -> set[str]:
        return set((await db.execute(select(KnowledgeWorkspaceBinding.id))).scalars()) & both

    with as_viewer(owner.id):
        assert await visible() == set()
        assert await db.get(KnowledgeWorkspaceBinding, reads_foreign.id) is None
    with as_viewer(other.id):
        assert await visible() == both
