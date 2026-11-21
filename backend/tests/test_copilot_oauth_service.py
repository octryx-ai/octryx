import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import LLMProvider, StoredSecret
from app.services.copilot_oauth import (
    COPILOT_OAUTH_CLIENT_ID,
    build_copilot_access_token,
    get_copilot_oauth_client_id,
    persist_copilot_oauth_tokens,
    require_copilot_oauth_client_id,
)
from app.services.provider.oauth_config_bridge import read_oauth_metadata, write_oauth_metadata
from app.services.secret import get_secret_value, set_secret_value
from app.time_utils import utc_now


def test_get_copilot_oauth_client_id_uses_configured_value(monkeypatch):
    class FakeSettings:
        copilot_oauth_client_id = "custom-client-id"

    monkeypatch.setattr("app.services.copilot_oauth.service.get_settings", lambda: FakeSettings())

    assert get_copilot_oauth_client_id() == "custom-client-id"


def test_get_copilot_oauth_client_id_returns_empty_when_unconfigured(monkeypatch):
    class FakeSettings:
        copilot_oauth_client_id = ""

    monkeypatch.setattr("app.services.copilot_oauth.service.get_settings", lambda: FakeSettings())

    assert get_copilot_oauth_client_id() == COPILOT_OAUTH_CLIENT_ID == ""


def test_require_copilot_oauth_client_id_rejects_unconfigured_value(monkeypatch):
    class FakeSettings:
        copilot_oauth_client_id = ""

    monkeypatch.setattr("app.services.copilot_oauth.service.get_settings", lambda: FakeSettings())

    with pytest.raises(ValueError, match="COPILOT_OAUTH_CLIENT_ID must be configured"):
        require_copilot_oauth_client_id()


@pytest.mark.asyncio
async def test_persist_copilot_oauth_tokens_stores_access_refresh_and_metadata(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot Enterprise",
        auth_mode="oauth",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_fetch_profile(access_token: str):
        assert access_token == "access-token-1"
        return {"login": "alice-example", "name": "Alice Example"}

    result = await persist_copilot_oauth_tokens(
        db,
        provider=provider,
        token_data={
            "access_token": "access-token-1",
            "refresh_token": "refresh-token-1",
            "token_type": "bearer",
            "expires_in": 3600,
            "refresh_token_expires_in": 7200,
        },
        set_secret_value_func=set_secret_value,
        fetch_profile_func=fake_fetch_profile,
    )

    await db.refresh(provider)
    secrets = (await db.execute(select(StoredSecret).order_by(StoredSecret.field_name.asc()))).scalars().all()

    assert provider.auth_mode == "oauth"
    assert provider.api_key_secret_ref is not None
    meta = await read_oauth_metadata(db, provider)
    assert meta["source"] == "github_device_flow"
    assert meta["login"] == "alice-example"
    assert meta["name"] == "Alice Example"
    assert meta["access_token_expires_at"]
    assert meta["refresh_token_expires_at"]
    assert result["login"] == "alice-example"
    assert [secret.field_name for secret in secrets] == ["api_key", "refresh_token"]
    assert await get_secret_value(db, secret_id=provider.api_key_secret_ref) == "access-token-1"
    assert (
        await get_secret_value(
            db,
            tool_name=f"control_plane_provider:{provider.id}",
            field_name="refresh_token",
            project_id=None,
        )
        == "refresh-token-1"
    )


@pytest.mark.asyncio
async def test_build_copilot_access_token_refreshes_expired_token(db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot Enterprise",
        auth_mode="oauth",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()
    await write_oauth_metadata(
        db,
        provider,
        {
            "access_token_expires_at": (utc_now() - timedelta(minutes=10)).isoformat(),
            "source": "github_device_flow",
            "host": "https://github.com",
        },
    )
    await db.commit()

    access_secret = await set_secret_value(
        db,
        tool_name=f"control_plane_provider:{provider.id}",
        field_name="api_key",
        project_id=None,
        value="expired-access-token",
    )
    refresh_secret = await set_secret_value(
        db,
        tool_name=f"control_plane_provider:{provider.id}",
        field_name="refresh_token",
        project_id=None,
        value="refresh-token-1",
    )
    provider.api_key_secret_ref = access_secret.id
    await db.commit()

    async def fake_refresh(refresh_token: str):
        assert refresh_token == "refresh-token-1"
        return {
            "access_token": "fresh-access-token",
            "refresh_token": "refresh-token-2",
            "token_type": "bearer",
            "expires_in": 1800,
            "refresh_token_expires_in": 7200,
        }

    async def fake_fetch_profile(access_token: str):
        assert access_token == "fresh-access-token"
        return {"login": "alice-example", "name": "Alice Example"}

    monkeypatch.setattr("app.services.copilot_oauth.service.refresh_copilot_access_token", fake_refresh)
    monkeypatch.setattr("app.services.copilot_oauth.service.fetch_github_user_profile", fake_fetch_profile)

    token = await build_copilot_access_token(
        db,
        provider=provider,
        get_secret_value_func=get_secret_value,
        set_secret_value_func=set_secret_value,
    )

    await db.refresh(provider)
    assert token == "fresh-access-token"
    assert provider.api_key_secret_ref == access_secret.id
    meta = await read_oauth_metadata(db, provider)
    assert meta["login"] == "alice-example"
    assert meta["access_token_expires_at"]
    assert meta["refresh_token_expires_at"]
    assert await get_secret_value(db, secret_id=provider.api_key_secret_ref) == "fresh-access-token"
    assert (
        await get_secret_value(
            db,
            tool_name=f"control_plane_provider:{provider.id}",
            field_name="refresh_token",
            project_id=None,
        )
        == "refresh-token-2"
    )
    assert refresh_secret.id != ""
