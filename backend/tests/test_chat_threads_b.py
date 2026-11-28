"""A stale running thread without a live worker continues on a runner."""

import uuid

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Project, Session, User
from tests.chat_pool_support import chat_pool  # noqa: F401 - fixture
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_continue_allows_stale_running_session_without_live_worker(client, db, chat_pool):  # noqa: F811
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="running",
        metadata_={"title": "Stale running thread"},
    )
    db.add(session)
    await db.commit()

    continue_resp = await client.post(f"/admin/chat/api/sessions/{session.id}/continue", json={})
    assert continue_resp.status_code == 200, continue_resp.text
    assert continue_resp.json()["selectedSession"]["id"] == session.id
    job = (await db.execute(select(DeviceJob).where(DeviceJob.session_id == session.id))).scalar_one()
    assert job.device_id == chat_pool.id and "Do not restart from scratch" in job.turn_prompt
