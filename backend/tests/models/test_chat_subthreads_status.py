"""A terminal parent status propagates recursively to active descendants, and archiving and restoring a parent thread handles mixed child statuses."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Session, User


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_bootstrap_propagates_terminal_parent_status_recursively_to_active_descendants(admin_client, db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="error",
        metadata_={"title": "Broken root", "stop_reason": "parent_failed"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Still active child"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    grandchild_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={"title": "Still active grandchild"},
        parent_session_id=child_session.id,
        sub_agent_depth=2,
    )
    db.add_all([parent_session, child_session, grandchild_session])
    await db.commit()

    bootstrap_resp = await admin_client.get(f"/admin/chat/api/bootstrap?session_id={parent_session.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()

    group = next(group for group in payload["activeThreadGroups"] if group["projectName"] == "acme-orders")
    parent_row = next(session for session in group["sessions"] if session["id"] == parent_session.id)
    assert parent_row["status"] == "error"
    child_row = parent_row["subThreads"][0]
    assert child_row["status"] == "error"
    grandchild_row = child_row["subThreads"][0]
    assert grandchild_row["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_archiving_and_restoring_parent_thread_handles_mixed_child_statuses(admin_client, db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Parent restore test"},
    )
    child_sessions = [
        Session(
            id=str(uuid.uuid4()),
            user_id=admin_user.id,
            project_id=project.id,
            agent_type="diagnosis",
            status=status,
            metadata_={"title": title},
            parent_session_id=parent_session.id,
            sub_agent_depth=1,
        )
        for status, title in [
            ("active", "Child active"),
            ("pending_approval", "Child approval"),
            ("error", "Child error"),
        ]
    ]
    db.add(parent_session)
    db.add_all(child_sessions)
    await db.commit()

    archive_resp = await admin_client.post(f"/admin/chat/api/sessions/{parent_session.id}/archive")
    assert archive_resp.status_code == 200
    for session in [parent_session, *child_sessions]:
        await db.refresh(session)
        assert session.status == "archived"

    restore_resp = await admin_client.post(f"/admin/chat/api/sessions/{parent_session.id}/restore")
    assert restore_resp.status_code == 200
    for session in [parent_session, *child_sessions]:
        await db.refresh(session)
        assert session.status == "active"
