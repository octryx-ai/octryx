"""Tests for subthread management, bootstrap nesting, and bootstrap parent status."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, Project, Session, User


@pytest.mark.asyncio
async def test_admin_chat_bootstrap_nests_subthreads_under_parent(admin_client, db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Parent thread"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Child thread"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    db.add(parent_session)
    db.add(child_session)
    await db.commit()

    bootstrap_resp = await admin_client.get(f"/admin/chat/api/bootstrap?session_id={parent_session.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()

    group = next(group for group in payload["activeThreadGroups"] if group["projectName"] == "acme-orders")
    parent_row = next(session for session in group["sessions"] if session["id"] == parent_session.id)
    assert parent_row["subThreadCount"] == 1
    assert len(parent_row["subThreads"]) == 1
    assert parent_row["subThreads"][0]["id"] == child_session.id
    assert not any(session["id"] == child_session.id for session in group["sessions"])


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_bootstrap_selecting_child_session_keeps_parent_thread_group_context(admin_client, db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Parent orchestration thread"},
    )
    child_a = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={"title": "Child A"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    child_b = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={"title": "Child B"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    db.add_all([parent_session, child_a, child_b])
    await db.commit()

    bootstrap_resp = await admin_client.get(f"/admin/chat/api/bootstrap?session_id={child_b.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()

    assert payload["selectedSession"]["id"] == child_b.id
    group = next(group for group in payload["activeThreadGroups"] if group["projectName"] == "acme-orders")
    assert not any(session["id"] in {child_a.id, child_b.id} for session in group["sessions"])
    parent_row = next(session for session in group["sessions"] if session["id"] == parent_session.id)
    assert parent_row["subThreadCount"] == 2
    assert {child["id"] for child in parent_row["subThreads"]} == {child_a.id, child_b.id}
    selected_child_row = next(child for child in parent_row["subThreads"] if child["id"] == child_b.id)
    assert selected_child_row["status"] == "pending_approval"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_bootstrap_nests_grandchild_threads_recursively_under_root_parent(admin_client, db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Root parent"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Child level"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    grandchild_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={"title": "Grandchild level"},
        parent_session_id=child_session.id,
        sub_agent_depth=2,
    )
    approval = Approval(
        id=str(uuid.uuid4()),
        task_run_id=None,
        session_id=grandchild_session.id,
        requested_by=admin_user.id,
        action="Approve command execution for bash",
        status="pending",
        reason="Diagnosis mode requires approval\nCommand: python3 manage.py migrate",
    )
    db.add_all([parent_session, child_session, grandchild_session, approval])
    await db.commit()

    bootstrap_resp = await admin_client.get(f"/admin/chat/api/bootstrap?session_id={grandchild_session.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()

    assert payload["selectedSession"]["id"] == grandchild_session.id
    group = next(group for group in payload["activeThreadGroups"] if group["projectName"] == "acme-orders")
    parent_row = next(session for session in group["sessions"] if session["id"] == parent_session.id)
    assert parent_row["subThreadCount"] == 1
    child_row = parent_row["subThreads"][0]
    assert child_row["id"] == child_session.id
    assert child_row["subThreadCount"] == 1
    grandchild_row = child_row["subThreads"][0]
    assert grandchild_row["id"] == grandchild_session.id
    assert grandchild_row["status"] == "pending_approval"
    assert grandchild_row["pendingApprovalCount"] == 1
