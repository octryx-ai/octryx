"""A link to a thread that does not exist or is not the user's says so; it never opens another thread (X2)."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Session, User
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_bootstrap_reports_a_missing_thread_instead_of_opening_the_latest(client, db):
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    latest = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, status="active",
                     agent_type="change")
    db.add(latest)
    await db.commit()

    missing = (await client.get(f"/chat/api/bootstrap?session_id={uuid.uuid4()}")).json()
    assert missing["requestedSessionNotFound"] is True
    assert missing["selectedSession"] is None

    found = (await client.get(f"/chat/api/bootstrap?session_id={latest.id}")).json()
    assert found["requestedSessionNotFound"] is False
    assert found["selectedSession"]["id"] == latest.id

