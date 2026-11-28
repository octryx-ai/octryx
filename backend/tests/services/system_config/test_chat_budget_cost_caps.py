"""DB-backed runtime cost caps, project overrides of the request cost guard and runtime setting schema bounds."""

import uuid

import pytest
from sqlalchemy import select

from app.exceptions.tool import BudgetLimitExceededError
from app.models import LLMModel, LLMProvider, Project, Session, User
from app.services.budget import enforce_budget_limits
from app.services.system_config import (
    AGENT_REQUEST_COST_LIMIT_USD_KEY,
    AGENT_SESSION_COST_LIMIT_USD_KEY,
    set_system_config_value,
)


@pytest.mark.asyncio
async def test_runtime_settings_cost_caps_are_db_backed(admin_client, db, monkeypatch):
    get_resp = await admin_client.get("/admin/chat/api/panel/runtime-settings")
    assert get_resp.status_code == 200
    initial = get_resp.json()
    assert initial["agent_session_cost_limit_usd"] == 50
    assert initial["agent_request_cost_limit_usd"] == 10

    update_resp = await admin_client.put(
        "/admin/chat/api/panel/runtime-settings",
        json={
            "agent_session_cost_limit_usd": 2.5,
            "agent_request_cost_limit_usd": 0.01,
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["agent_session_cost_limit_usd"] == 2.5
    assert updated["agent_request_cost_limit_usd"] == 0.01

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin_user.id, status="active")
    provider = LLMProvider(id=str(uuid.uuid4()), name="bedrock", driver="bedrock_api", display_name="Bedrock", is_active=True)
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="expensive-model",
        pricing_input=20.0,
        pricing_output=0.0,
        is_active=True,
    )
    db.add_all([session, provider, model])
    await db.commit()
    monkeypatch.setenv("OCTRYX_AGENT_REQUEST_COST_LIMIT_USD", "99")

    with pytest.raises(BudgetLimitExceededError) as exc:
        await enforce_budget_limits(
            db,
            session_id=session.id,
            user_id=admin_user.id,
            project_id=None,
            runtimes=[{"provider_name": "bedrock", "model": "expensive-model"}],
            messages=[{"role": "user", "content": "x" * 4000}],
            max_completion_tokens=0,
            approx_chars_per_token=4,
        )

    assert exc.value.policy_name == "Default agent request cost guard"

    await set_system_config_value(db, key=AGENT_REQUEST_COST_LIMIT_USD_KEY, value=None)
    await set_system_config_value(db, key=AGENT_SESSION_COST_LIMIT_USD_KEY, value=None)
    await db.commit()


@pytest.mark.asyncio
async def test_runtime_settings_project_cost_caps_override_global(admin_client, db):
    project = Project(id=str(uuid.uuid4()), name="project-cost-caps", config={}, is_active=True)
    db.add(project)
    await db.commit()

    update_resp = await admin_client.put(
        f"/admin/chat/api/panel/runtime-settings?project_id={project.id}",
        json={
            "agent_session_cost_limit_usd": 0,
            "agent_request_cost_limit_usd": 0.01,
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["agent_session_cost_limit_usd"] == 0
    assert updated["agent_request_cost_limit_usd"] == 0.01
    assert updated["cost_limit_scope"]["scope"] == "project"
    assert updated["cost_limit_scope"]["request_source"] == "project"

    get_resp = await admin_client.get(f"/admin/chat/api/panel/runtime-settings?project_id={project.id}")
    assert get_resp.status_code == 200
    scoped = get_resp.json()
    assert scoped["agent_request_cost_limit_usd"] == 0.01
    assert scoped["cost_limit_scope"]["project_id"] == project.id

    stored_project = await db.get(Project, project.id)
    assert stored_project is not None
    assert stored_project.config["runtime_cost_limits"]["agent_request_cost_limit_usd"] == "0.01"


@pytest.mark.asyncio
async def test_project_request_cost_guard_overrides_global_default(db):
    await set_system_config_value(db, key=AGENT_REQUEST_COST_LIMIT_USD_KEY, value="99")
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name="project-request-cost-guard",
        config={
            "runtime_cost_limits": {
                "agent_session_cost_limit_usd": "0",
                "agent_request_cost_limit_usd": "0.01",
            },
        },
        is_active=True,
    )
    session = Session(id=str(uuid.uuid4()), user_id=admin_user.id, project_id=project.id, status="active")
    provider_name = f"bedrock-project-{uuid.uuid4().hex}"
    provider = LLMProvider(id=str(uuid.uuid4()), name=provider_name, display_name="Bedrock", is_active=True)
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="project-expensive-model",
        pricing_input=20.0,
        pricing_output=0.0,
        is_active=True,
    )
    db.add_all([project, session, provider, model])
    await db.commit()

    with pytest.raises(BudgetLimitExceededError) as exc:
        await enforce_budget_limits(
            db,
            session_id=session.id,
            user_id=admin_user.id,
            project_id=project.id,
            runtimes=[{"provider_name": provider_name, "model": "project-expensive-model"}],
            messages=[{"role": "user", "content": "x" * 4000}],
            max_completion_tokens=0,
            approx_chars_per_token=4,
        )

    assert exc.value.policy_name == "Default agent request cost guard"
    await set_system_config_value(db, key=AGENT_REQUEST_COST_LIMIT_USD_KEY, value=None)
    await db.commit()


@pytest.mark.asyncio
async def test_project_zero_request_cost_guard_disables_global_default(db):
    await set_system_config_value(db, key=AGENT_REQUEST_COST_LIMIT_USD_KEY, value="0.000001")
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name="project-request-cost-disabled",
        config={
            "runtime_cost_limits": {
                "agent_session_cost_limit_usd": "0",
                "agent_request_cost_limit_usd": "0",
            },
        },
        is_active=True,
    )
    session = Session(id=str(uuid.uuid4()), user_id=admin_user.id, project_id=project.id, status="active")
    provider_name = f"bedrock-project-{uuid.uuid4().hex}"
    provider = LLMProvider(id=str(uuid.uuid4()), name=provider_name, display_name="Bedrock", is_active=True)
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="project-disabled-model",
        pricing_input=20.0,
        pricing_output=0.0,
        is_active=True,
    )
    db.add_all([project, session, provider, model])
    await db.commit()

    await enforce_budget_limits(
        db,
        session_id=session.id,
        user_id=admin_user.id,
        project_id=project.id,
        runtimes=[{"provider_name": provider_name, "model": "project-disabled-model"}],
        messages=[{"role": "user", "content": "x" * 4000}],
        max_completion_tokens=0,
        approx_chars_per_token=4,
    )

    await set_system_config_value(db, key=AGENT_REQUEST_COST_LIMIT_USD_KEY, value=None)
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_runtime_settings_rejects_values_below_schema_floor(admin_client):
    update_resp = await admin_client.put(
        "/admin/chat/api/panel/runtime-settings",
        json={"max_output_tokens_default": 1},
    )
    assert update_resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_runtime_settings_rejects_values_above_schema_ceiling(admin_client):
    update_resp = await admin_client.put(
        "/admin/chat/api/panel/runtime-settings",
        json={"runtime_request_timeout_seconds": 999999},
    )
    assert update_resp.status_code == 422
