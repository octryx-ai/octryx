"""Independent authoring probes: a non-key must never become the default mode."""
import pytest
from sqlalchemy import func, select

from app.models import Project, Task
from app.models.integration.webhook import Webhook
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["tasks", "webhooks", "rest_webhooks"])
async def test_punctuation_only_mode_is_refused_without_creating_target(client, db, surface):
    project_id = (await db.execute(select(Project.id))).scalars().first()
    model = Task if surface == "tasks" else Webhook
    before = (await db.execute(select(func.count(model.id)))).scalar_one()
    if surface == "rest_webhooks":
        login = await client.post(
            "/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD}
        )
        assert login.status_code == 200
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        url = "/api/v1/webhooks"
    else:
        login = await client.post(
            "/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD}
        )
        assert login.status_code == 303
        headers = {}
        url = f"/admin/chat/api/panel/{surface}"
    response = await client.post(
        url,
        headers=headers,
        json={"name": "Root malformed mode probe", "project_id": project_id, "agent_type": "!!!"},
    )
    assert response.status_code == 422, "Explicit non-key silently became an accepted default mode"
    await db.rollback()
    after = (await db.execute(select(func.count(model.id)))).scalar_one()
    assert after == before
