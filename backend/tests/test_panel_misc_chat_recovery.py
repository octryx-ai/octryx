"""The chat send API recovers from a transitional response, and the parent thread bootstrap exposes a subthread's pending approval."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, Project, Session, User
from tests.conftest import ADMIN_PASSWORD
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_bootstrap_parent_thread_exposes_subthread_pending_approval_state(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Parent builder"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={"title": "Child approval"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    approval = Approval(
        id=str(uuid.uuid4()),
        task_run_id=None,
        session_id=child_session.id,
        requested_by=admin_user.id,
        action="Approve command execution for bash",
        status="pending",
        reason="Diagnosis mode requires approval\nCommand: python3 manage.py migrate",
    )
    db.add(parent_session)
    db.add(child_session)
    db.add(approval)
    await db.commit()

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={parent_session.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()

    group = next(group for group in payload["activeThreadGroups"] if group["projectName"] == "acme-orders")
    parent_row = next(session for session in group["sessions"] if session["id"] == parent_session.id)
    assert parent_row["subThreadCount"] == 1
    assert parent_row["subThreads"][0]["id"] == child_session.id
    assert parent_row["subThreads"][0]["status"] == "pending_approval"
    assert parent_row["subThreads"][0]["pendingApprovalCount"] == 1
