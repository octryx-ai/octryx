import uuid

import pytest

from app.models import LLMProvider
from app.services.admin.provider.admin_copilot_service import poll_copilot_device_login, start_copilot_device_flow


@pytest.mark.asyncio
async def test_start_copilot_device_flow_returns_configured_client_id(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot Provider",
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
            "client_id": "configured-client-id",
        }

    flow_state = {}
    result = await start_copilot_device_flow(
        db,
        provider_id=provider.id,
        flow_state=flow_state,
        begin_flow_func=fake_begin_flow,
    )

    assert result["client_id"] == "configured-client-id"
    assert flow_state[result["flow_id"]]["client_id"] == "configured-client-id"


@pytest.mark.asyncio
async def test_poll_copilot_device_login_reports_token_storage_failure(db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot Provider",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_poll_flow(device_code: str):
        assert device_code == "device-code-123"
        return {"access_token": "access-token-123"}

    async def fake_persist(*args, **kwargs):
        raise RuntimeError("secret backend unavailable")

    monkeypatch.setattr("app.services.admin.provider.admin_copilot_service.persist_copilot_oauth_tokens", fake_persist)

    flow_state = {
        "flow-1": {
            "provider_id": provider.id,
            "device_code": "device-code-123",
            "status": "pending",
            "error": "",
        }
    }
    result = await poll_copilot_device_login(
        db,
        provider_id=provider.id,
        flow_id="flow-1",
        flow_state=flow_state,
        poll_flow_func=fake_poll_flow,
        provider_secret_scope_func=lambda provider: ("tool", "api_key"),
        set_secret_value_func=lambda *args, **kwargs: None,
        fetch_profile_func=lambda access_token: None,
    )

    assert result == {
        "status": "failed",
        "error": "GitHub login succeeded, but token storage failed. token_storage_failed error_type=RuntimeError",
    }
    assert flow_state["flow-1"]["status"] == "failed"


@pytest.mark.asyncio
async def test_poll_copilot_device_login_returns_only_the_github_error_code(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot Provider",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_poll_flow(device_code: str):
        assert device_code == "device-code-123"
        return {
            "error": "expired_token",
            "error_description": "The device code has expired.",
        }

    flow_state = {
        "flow-1": {
            "provider_id": provider.id,
            "device_code": "device-code-123",
            "status": "pending",
            "error": "",
        }
    }
    result = await poll_copilot_device_login(
        db,
        provider_id=provider.id,
        flow_id="flow-1",
        flow_state=flow_state,
        poll_flow_func=fake_poll_flow,
        provider_secret_scope_func=lambda provider: ("tool", "api_key"),
        set_secret_value_func=lambda *args, **kwargs: None,
        fetch_profile_func=lambda access_token: None,
    )

    assert result == {"status": "failed", "error": "expired_token"}
    assert flow_state["flow-1"]["error"] == "expired_token"
