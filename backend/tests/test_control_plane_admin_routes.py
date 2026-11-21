"""Admin runtime target routes, promotion, Copilot provider setup and login, and the test chat."""

import uuid

import pytest
from sqlalchemy import select

from app.models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMProvider
from app.services.control_plane_service import upsert_runtime_target
from app.services.provider.oauth_config_bridge import read_oauth_metadata
from app.services.secret import get_secret_value
from tests.conftest import ADMIN_PASSWORD
from tests.control_plane_support import _clear_runtime_targets, _set_provider_api_key_secret


@pytest.mark.asyncio
async def test_admin_runtime_target_toggle_and_delete_routes_delegate_correctly(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Toggle Provider",
        default_model_id="stepfun/step-3.5-flash:free",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    await _set_provider_api_key_secret(db, provider, "toggle-key")

    target = await upsert_runtime_target(
        db,
        provider=provider,
        model_id="stepfun/step-3.5-flash:free",
        make_primary=True,
        is_active=True,
    )
    await db.commit()
    target_id = target.id

    calls = {"toggle": None, "delete": None}

    async def fake_toggle(db_session, target_id):
        calls["toggle"] = target_id
        return await db_session.get(ControlPlaneRuntimeTarget, target_id)

    async def fake_delete(db_session, target_id):
        calls["delete"] = target_id
        existing = await db_session.get(ControlPlaneRuntimeTarget, target_id)
        if existing is not None:
            await db_session.delete(existing)
            await db_session.flush()
        return True

    monkeypatch.setattr("app.web.routers.control_plane_runtime_targets.toggle_runtime_target", fake_toggle)
    monkeypatch.setattr("app.web.routers.control_plane_runtime_targets.delete_runtime_target", fake_delete)

    toggle_resp = await client.post(f"/admin/control-plane/runtime-targets/{target_id}/toggle")
    assert toggle_resp.status_code == 303
    assert calls["toggle"] == target_id

    delete_resp = await client.post(f"/admin/control-plane/runtime-targets/{target_id}/delete")
    assert delete_resp.status_code == 303
    assert calls["delete"] == target_id

    db.expire_all()
    deleted_target = await db.get(ControlPlaneRuntimeTarget, target_id)
    assert deleted_target is None


@pytest.mark.asyncio
async def test_admin_save_with_promote_adds_highest_priority_runtime_target(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    save_resp = await client.post(
        "/admin/control-plane/save",
        data={
            "driver": "openrouter_api",
            "display_name": "Promoted OpenRouter",
            "api_key": "ui-key",
            "model_id": "stepfun/step-3.5-flash:free",
            "is_active": "true",
            "set_as_active": "true",
        },
    )
    assert save_resp.status_code == 303

    await db.rollback()
    provider = (
        await db.execute(select(LLMProvider).where(LLMProvider.display_name == "Promoted OpenRouter"))
    ).scalar_one()
    config = (await db.execute(select(ControlPlaneConfig).where(ControlPlaneConfig.name == "default"))).scalar_one()
    assert config.provider_id == provider.id
    assert config.model_id == "stepfun/step-3.5-flash:free"
    assert provider.api_key_secret_ref
    assert await get_secret_value(db, secret_id=provider.api_key_secret_ref) == "ui-key"


@pytest.mark.asyncio
async def test_admin_can_save_copilot_provider_with_auth_session_mode(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    monkeypatch.setattr(
        "app.web._helpers.control_plane.get_copilot_auth_session_info",
        lambda: {"available": True, "login": "alice-example", "host": "https://github.com", "model": "gpt-5.3-codex"},
    )

    save_resp = await client.post(
        "/admin/control-plane/save",
        data={
            "driver": "copilot_api",
            "display_name": "Copilot OAuth",
            "auth_mode": "auth_session",
            "model_id": "gpt-4o",
            "is_active": "true",
        },
    )
    assert save_resp.status_code == 303

    await db.rollback()
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.display_name == "Copilot OAuth"))).scalar_one()
    assert provider.auth_mode == "auth_session"
    assert provider.api_key_secret_ref is None


@pytest.mark.asyncio
async def test_admin_can_complete_copilot_github_login_flow(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot GitHub Login",
        auth_mode="oauth",
        default_model_id="gpt-4o",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_begin_flow():
        return {
            "device_code": "device-code-123",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
        }

    async def fake_poll_flow(device_code):
        return {"access_token": "oauth-token-123"}

    async def fake_fetch_profile(access_token):
        return {"login": "alice-example", "name": "Alice Example"}

    monkeypatch.setattr("app.web.routers.control_plane.begin_copilot_device_flow", fake_begin_flow)
    monkeypatch.setattr("app.web.routers.control_plane.poll_copilot_device_flow", fake_poll_flow)
    monkeypatch.setattr("app.web.routers.control_plane.fetch_github_user_profile", fake_fetch_profile)

    start_resp = await client.post(
        "/admin/control-plane/copilot/device/start",
        data={"provider_id": provider.id},
    )
    assert start_resp.status_code == 303
    location = start_resp.headers["location"]
    assert "copilot_flow_id=" in location
    flow_id = location.split("copilot_flow_id=", 1)[1]

    page_resp = await client.get(location)
    assert page_resp.status_code == 200
    assert "Complete GitHub verification" in page_resp.text
    assert "ABCD-EFGH" in page_resp.text

    complete_resp = await client.post(
        "/admin/control-plane/copilot/device/complete",
        data={"provider_id": provider.id, "flow_id": flow_id},
    )
    assert complete_resp.status_code == 303

    await db.rollback()
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == provider.id))).scalar_one()
    assert provider.auth_mode == "oauth"
    assert provider.api_key_secret_ref
    meta = await read_oauth_metadata(db, provider)
    assert meta["login"] == "alice-example"
    assert await get_secret_value(db, secret_id=provider.api_key_secret_ref) == "oauth-token-123"


@pytest.mark.asyncio
async def test_admin_control_plane_test_chat_uses_runtime_chain(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    await _clear_runtime_targets(db)
    primary_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Primary OpenRouter",
        default_model_id="stepfun/step-3.5-flash:free",
        is_global=True,
        is_active=True,
    )
    fallback_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Fallback OpenRouter",
        default_model_id="nvidia/nemotron-3-super-120b-a12b:free",
        is_global=True,
        is_active=True,
    )
    db.add(primary_provider)
    db.add(fallback_provider)
    await db.flush()
    await _set_provider_api_key_secret(db, primary_provider, "primary-key")
    await _set_provider_api_key_secret(db, fallback_provider, "fallback-key")

    await upsert_runtime_target(db, provider=fallback_provider, model_id="nvidia/nemotron-3-super-120b-a12b:free")
    await upsert_runtime_target(
        db,
        provider=primary_provider,
        model_id="stepfun/step-3.5-flash:free",
        make_primary=True,
    )
    await db.commit()

    class FakeProvider:
        def __init__(self, token):
            self.token = token

        async def chat(self, messages, model, tools=None, temperature=0, max_tokens=4096):
            if self.token == "primary-key":
                raise RuntimeError("temporary provider outage")
            return {
                "content": "chat-ok",
                "tool_calls": None,
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "model": model,
            }

        async def close(self):
            return None

    monkeypatch.setattr(
        "app.agent.engine.get_provider",
        lambda provider_name=None, api_key=None, region=None, role_arn=None, copilot_token=None: FakeProvider(
            api_key or copilot_token
        ),
    )

    resp = await client.post(
        "/admin/control-plane/test-chat",
        data={"prompt": "test prompt"},
    )
    assert resp.status_code == 200
    assert "chat-ok" in resp.text
