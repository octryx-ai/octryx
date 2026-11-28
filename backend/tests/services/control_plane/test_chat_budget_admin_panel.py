"""Admin budget policy and identity provider routes, the cost chargeback report and panel input validation."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.models import CostAllocationRule, LLMProvider, Project, Session, UsageEvent, User
from app.services.control_plane_service import upsert_runtime_target
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_admin_budget_policies_route_create_and_list(admin_client, db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    create_resp = await admin_client.post(
        "/admin/budget-policies",
        json={
            "name": "Admin daily request cap",
            "user_id": admin_user.id,
            "daily_request_limit": 25,
            "warn_at_percent": 80,
            "block_at_percent": 100,
            "is_active": True,
        },
    )
    assert create_resp.status_code == 200
    payload = create_resp.json()
    assert payload["name"] == "Admin daily request cap"
    assert payload["userId"] == admin_user.id
    assert payload["dailyRequestLimit"] == 25

    list_resp = await admin_client.get("/admin/budget-policies")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(item["id"] == payload["id"] for item in items)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_panel_identity_provider_create_and_list(admin_client):
    create_resp = await admin_client.post(
        "/admin/chat/api/panel/identity-providers",
        json={
            "name": "GitHub OIDC",
            "provider_type": "oidc",
            "issuer_url": "https://github.com",
            "client_id": "client-1",
            "authorization_endpoint": "https://github.com/login/oauth/authorize",
            "token_endpoint": "https://github.com/login/oauth/access_token",
            "userinfo_endpoint": "https://api.github.com/user",
            "scopes": ["openid", "profile", "email"],
            "is_active": True,
        },
    )
    assert create_resp.status_code == 200
    payload = create_resp.json()
    assert payload["name"] == "GitHub OIDC"
    assert payload["providerType"] == "oidc"

    list_resp = await admin_client.get("/admin/chat/api/panel/identity-providers")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(item["id"] == payload["id"] for item in items)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_cost_chargeback_api_and_panel_report(client, auth_headers, db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.flush()
    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=session.id,
            user_id=auth_user.id,
            provider="openrouter",
            model="gpt-test",
            tokens_in=100,
            tokens_out=50,
            cost=1.75,
            created_at=datetime(2026, 3, 12, 10, 0, tzinfo=UTC),
        )
    )
    await db.commit()

    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    # Seed an allocation rule for the report.
    db.add(CostAllocationRule(project_id=project.id, cost_center="ENG-OPS", percentage=100,
                              valid_from=date(2026, 3, 1)))
    await db.commit()

    api_report_resp = await client.get("/api/v1/reports/cost?period=2026-03", headers=auth_headers)
    assert api_report_resp.status_code == 200
    api_rows = api_report_resp.json()
    assert any(
        row["project_id"] == project.id
        and row["provider_id"] == "openrouter"
        and row["report"]["cost_centers"][0]["cost_center"] == "ENG-OPS"
        for row in api_rows
    )

    panel_report_resp = await client.get("/admin/chat/api/panel/reports/cost?period=2026-03")
    assert panel_report_resp.status_code == 200
    panel_rows = panel_report_resp.json()
    assert any(row["project_id"] == project.id and row["total_cost"] == pytest.approx(1.75) for row in panel_rows)
    assert (await client.get("/admin/chat/api/panel/cost-allocation-rules")).status_code in {404, 405}


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_panel_move_runtime_rejects_invalid_direction(admin_client, db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Move Provider",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    target = await upsert_runtime_target(
        db,
        provider=provider,
        model_id="test/model",
        make_primary=True,
        is_active=True,
    )
    await db.commit()

    move_resp = await admin_client.post(
        f"/admin/chat/api/panel/runtimes/{target.id}/move",
        json={"direction": "sideways"},
    )
    assert move_resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_tts_provider_requires_provider_name(admin_client):
    resp = await admin_client.post("/admin/chat/api/v1/tts/providers", json={"enabled": True})
    assert resp.status_code == 422
