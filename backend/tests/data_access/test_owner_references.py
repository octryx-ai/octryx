from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import InvalidRequestError

from app.models import Project, Session, Task, TaskRun, UsageEvent
from app.models.agent.approval import Approval
from app.models.security.policy_engine import PolicyDecisionLog
from app.services.access_control import get_project_role_for_user
from app.services.data_access import as_viewer
from app.services.data_access.read_filter import UnfilteredReadError
from app.services.project.private_workspace import ensure_private_workspace, refuse_foreign_private
from tests.devices.device_support import user_named
from tests.phased_workflow_fixtures import admin_user


@pytest.fixture
async def scene(db):
    owner = await user_named(db, f"refs-owner-{uuid.uuid4().hex[:6]}")
    admin = await admin_user(db)
    private = (await ensure_private_workspace(db, owner)).id
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=private, origin="chat")
    task = Task(name=f"refs-task-{uuid.uuid4().hex[:6]}", owner_id=owner.id, dispatch_binding="task_definition")
    db.add_all([session, task])
    await db.flush()
    run = TaskRun(task_id=task.id, session_id=session.id, status="running", started_by=owner.id)
    db.add(run)
    await db.flush()
    rows = {
        "session_approval": Approval(session_id=session.id, requested_by=owner.id, action="tool:shell"),
        "run_approval": Approval(task_run_id=run.id, requested_by=owner.id, action="tool:shell"),
        "usage": UsageEvent(session_id=session.id, user_id=owner.id, model="synthetic-model", cost=7.5),
    }
    db.add_all(rows.values())
    db.add(PolicyDecisionLog(point="tool", action="call", outcome="allow", mode="enforce", principal=owner.id,
                             resource="shell", decision="allow", legacy_decision="allow", schema_version="1",
                             session_id=session.id, reason="refs-decision"))
    await db.commit()
    db.expunge_all()
    return owner, admin, private, session.id, {name: row.id for name, row in rows.items()}


async def test_another_persons_private_workspace_is_no_project_for_a_viewer(db, scene):
    owner, admin, private, _session, _rows = scene
    with as_viewer(admin.id):
        assert private not in set((await db.execute(select(Project.id))).scalars())
        assert await db.get(Project, private) is None
    with as_viewer(owner.id):
        assert await db.get(Project, private) is not None


async def test_rows_without_a_workspace_follow_the_session_or_run_they_belong_to(db, scene):
    owner, admin, _private, _session, rows = scene
    approvals = select(Approval.id).where(Approval.id.in_([rows["session_approval"], rows["run_approval"]]))
    decisions = select(PolicyDecisionLog.id).where(PolicyDecisionLog.reason == "refs-decision")
    with as_viewer(admin.id):
        assert set((await db.execute(approvals)).scalars()) == set()
        assert (await db.execute(decisions)).first() is None
        assert await db.get(Approval, rows["run_approval"]) is None
    with as_viewer(owner.id):
        assert set((await db.execute(approvals)).scalars()) == {rows["session_approval"], rows["run_approval"]}
        assert (await db.execute(decisions)).first() is not None


async def test_a_child_row_queried_on_its_own_follows_its_parent(db, scene):
    owner, admin, _private, session_id, _rows = scene
    total = select(func.coalesce(func.sum(UsageEvent.cost), 0)).where(UsageEvent.session_id == session_id)
    with as_viewer(admin.id):
        assert (await db.execute(total)).scalar_one() == 0
    with as_viewer(owner.id):
        assert (await db.execute(total)).scalar_one() == 7.5


async def test_core_and_text_reads_of_workspace_rows_are_refused_for_a_viewer(db, scene):
    _owner, admin, _private, _session, _rows = scene
    with as_viewer(admin.id):
        with pytest.raises(UnfilteredReadError, match="Core read of sessions"):
            await db.execute(select(Session.__table__))
        with pytest.raises(UnfilteredReadError, match="Core read of usage_events"):
            await db.execute(select(func.count()).select_from(UsageEvent.__table__.join(
                Session, UsageEvent.session_id == Session.id)))
        with pytest.raises(UnfilteredReadError, match="text SQL"):
            await db.execute(text("SELECT id FROM sessions"))


async def test_a_hidden_row_already_in_the_session_reads_as_gone_on_refresh(db, scene):
    _owner, admin, _private, session_id, _rows = scene
    loaded = await db.get(Session, session_id)
    with as_viewer(admin.id):
        with pytest.raises(InvalidRequestError):
            await db.refresh(loaded)
        db.expire(loaded)
        assert await db.get(Session, session_id) is None


async def test_a_workspace_check_still_knows_a_hidden_private_workspace(db, scene):
    _owner, admin, private, _session, _rows = scene
    with as_viewer(admin.id):
        assert await refuse_foreign_private(db, private, admin.id) is True
        assert await get_project_role_for_user(db, admin.id, private) is None
