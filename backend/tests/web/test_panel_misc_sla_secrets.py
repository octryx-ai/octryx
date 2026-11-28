"""Branding, cookie token logging, SLA definitions and breaches, secret rotation and artifact action runs."""

import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Project, Task, TaskRun, User
from app.time_utils import utc_now
from app.web._helpers import chat_state as branding_module
from app.web._helpers.auth import _get_user_from_cookie
from tests.conftest import ADMIN_PASSWORD


def test_load_branding_config_logs_and_falls_back_on_invalid_json(tmp_path, monkeypatch, caplog):
    branding_file = tmp_path / "branding.json"
    branding_file.write_text("{invalid")
    monkeypatch.setattr(branding_module, "_BRANDING_DATA_FILE", branding_file)
    monkeypatch.setattr(get_settings(), "branding_enabled", True)

    with caplog.at_level(logging.ERROR):
        result = branding_module._load_branding_config()

    assert result == {"app_name": "Octryx", "logo_url": "", "logo_svg": "", "enabled": True}
    assert any("Failed to load branding config" in message for message in caplog.messages)


def test_get_user_from_cookie_logs_invalid_token(caplog):
    class FakeRequest:
        cookies = {"access_token": "bad-token"}
        headers = {}

    with caplog.at_level(logging.WARNING):
        result = _get_user_from_cookie(FakeRequest())

    assert result is None
    assert any("Failed to decode auth token" in message for message in caplog.messages)




@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_sla_definitions_and_breaches_can_be_managed_via_admin_api(admin_client, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Panel SLA Task",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
    )
    db.add(task)
    await db.commit()

    create_resp = await admin_client.post(
        "/admin/chat/api/panel/sla-definitions",
        json={
            "name": "Panel SLA",
            "task_id": task.id,
            "max_duration_seconds": 300,
            "alert_threshold": 0.75,
            "is_active": True,
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    definition = create_resp.json()
    assert definition["task_id"] == task.id

    list_resp = await admin_client.get("/admin/chat/api/panel/sla-definitions")
    assert list_resp.status_code == 200
    assert any(row["id"] == definition["id"] for row in list_resp.json())

    update_resp = await admin_client.put(
        f"/admin/chat/api/panel/sla-definitions/{definition['id']}",
        json={"agent_type": "diagnosis", "task_id": task.id, "max_duration_seconds": 600},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["max_duration_seconds"] == 600

    run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        started_by=admin.id,
        status="running",
        started_at=utc_now() - timedelta(seconds=700),
    )
    db.add(run)
    await db.commit()

    from app.services.sla import process_sla_breaches

    await process_sla_breaches(db)
    breaches_resp = await admin_client.get("/admin/chat/api/panel/sla-breaches?unresolved_only=true")
    assert breaches_resp.status_code == 200
    assert any(row["task_run_id"] == run.id for row in breaches_resp.json())

    delete_resp = await admin_client.delete(f"/admin/chat/api/panel/sla-definitions/{definition['id']}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "deleted"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_secret_rotation_panel_lists_updates_and_rotates_secrets(client, db):
    from app.services.secret import set_secret_value

    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    secret = await set_secret_value(
        db,
        tool_name="jira",
        field_name="api_token",
        project_id=None,
        value="initial-secret",
        expires_at=utc_now() + timedelta(days=7),
    )
    await db.commit()

    list_resp = await client.get("/admin/chat/api/panel/stored-secrets?expiring_within_days=30")
    assert list_resp.status_code == 200
    matching = next(row for row in list_resp.json() if row["id"] == secret.id)
    assert matching["tool_name"] == "jira"
    assert matching["days_until_expiry"] <= 7

    update_resp = await client.patch(
        f"/admin/chat/api/panel/stored-secrets/{secret.id}",
        json={"expires_at": (utc_now() + timedelta(days=14)).isoformat()},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["days_until_expiry"] >= 13

    rotate_resp = await client.post(
        f"/admin/chat/api/panel/stored-secrets/{secret.id}/rotate",
        json={
            "value": "rotated-secret",
            "expires_at": (utc_now() + timedelta(days=45)).isoformat(),
            "note": "manual rotation",
        },
    )
    assert rotate_resp.status_code == 200, rotate_resp.text
    assert rotate_resp.json()["last_rotated_at"] is not None

    log_resp = await client.get("/admin/chat/api/panel/secret-rotation-log?limit=20")
    assert log_resp.status_code == 200
    assert any(row["secret_id"] == secret.id and row["action"] == "rotated" for row in log_resp.json())
