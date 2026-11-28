"""Admin panel create endpoints reject invalid payloads at the schema boundary; outbound webhook CRUD lists deliveries."""

import uuid

import pytest
from sqlalchemy import select

from app.models import LLMProvider, Project, User
from app.services.outbound_webhook import emit_outbound_webhook_event


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_the_retired_agent_mode_schema_is_not_served(admin_client):
    resp = await admin_client.post("/admin/chat/api/panel/modes", json={"key": "triage-no-name", "name": ""})
    assert resp.status_code in {404, 405}




@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_task_create_rejects_zero_concurrency_at_schema_boundary(admin_client):
    resp = await admin_client.post(
        "/admin/chat/api/panel/tasks",
        json={"name": "Invalid Task", "max_concurrent_agents": 0, "dispatch_binding": "agent_definition"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_agent_builder_create_requires_name_at_schema_boundary(admin_client):
    resp = await admin_client.post(
        "/admin/chat/api/panel/agents",
        json={"name": "", "agent_type": "diagnosis"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_user_create_requires_minimum_password_length_at_schema_boundary(admin_client):
    resp = await admin_client.post(
        "/admin/chat/api/panel/users",
        json={
            "username": "shortpass",
            "email": "short@example.com",
            "password": "short",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_provider_create_requires_driver_at_schema_boundary(admin_client):
    resp = await admin_client.post("/admin/chat/api/panel/providers", json={"driver": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_provider_model_add_rejects_low_budgets_at_schema_boundary(admin_client, db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Schema Provider",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    resp = await admin_client.post(
        f"/admin/chat/api/panel/providers/{provider.id}/models",
        json={"model_id": "schema/model", "max_tokens_per_request": 10},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_webhook_create_requires_project_id_at_schema_boundary(admin_client):
    resp = await admin_client.post(
        "/admin/chat/api/panel/webhooks",
        json={"name": "Hook without project", "project_id": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_outbound_webhook_create_requires_url_at_schema_boundary(admin_client):
    resp = await admin_client.post(
        "/admin/chat/api/panel/outbound-webhooks",
        json={"name": "Outbound without URL", "url": "", "event_types": ["task.completed"]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_report_export_create_rejects_unknown_type_at_schema_boundary(admin_client):
    resp = await admin_client.post(
        "/admin/chat/api/panel/reports/export",
        json={"report_type": "made_up_report", "format": "json", "parameters": {}},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_runtime_add_requires_provider_id_at_schema_boundary(admin_client):
    resp = await admin_client.post(
        "/admin/chat/api/panel/runtimes",
        json={"provider_id": "", "model_id": "model/test"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_outbound_webhook_panel_crud_and_delivery_listing(admin_client, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    create_resp = await admin_client.post(
        "/admin/chat/api/panel/outbound-webhooks",
        json={
            "name": "Panel outbound",
            "url": "https://example.test/panel",
            "project_id": project.id,
            "event_types": ["session.completed", "task.completed"],
            "is_active": True,
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    webhook_id = create_resp.json()["id"]
    assert create_resp.json()["signing_secret"]

    await emit_outbound_webhook_event(
        db,
        event_type="session.completed",
        project_id=project.id,
        payload={"session_id": "panel-session"},
    )
    await db.commit()

    list_resp = await admin_client.get("/admin/chat/api/panel/outbound-webhooks")
    assert list_resp.status_code == 200
    assert any(item["id"] == webhook_id for item in list_resp.json())

    deliveries_resp = await admin_client.get("/admin/chat/api/panel/outbound-webhook-deliveries")
    assert deliveries_resp.status_code == 200
    assert any(item["event_type"] == "session.completed" for item in deliveries_resp.json())

    update_resp = await admin_client.put(
        f"/admin/chat/api/panel/outbound-webhooks/{webhook_id}",
        json={"is_active": False},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["is_active"] is False

    delete_resp = await admin_client.delete(f"/admin/chat/api/panel/outbound-webhooks/{webhook_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "deleted"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_channel_create_requires_plugin_id_at_schema_boundary(admin_client):
    resp = await admin_client.post(
        "/admin/chat/api/panel/channels",
        json={"plugin_id": "", "enabled": False, "config": {}},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_mcp_add_requires_name_at_schema_boundary(admin_client):
    resp = await admin_client.post(
        "/admin/chat/api/panel/mcp/servers",
        json={"name": "", "transport": "stdio"},
    )
    assert resp.status_code == 422
