import uuid

import pytest
from sqlalchemy import select

from app.agent.providers import GoogleClient, get_provider
from app.models import LLMProvider
from app.services.admin.provider.admin_provider_service import create_provider, update_provider
from app.services.control_plane_service import build_provider_client_kwargs_async
from app.services.provider.oauth_config_bridge import read_oauth_metadata, write_oauth_metadata


def test_google_factory_api_key():
    client = get_provider("google", driver="gemini_api", api_key="gemini-key", auth_mode="api_key")
    assert isinstance(client, GoogleClient)
    assert client.name == "google"
    assert client.api_key == "gemini-key"
    assert client.access_token is None


def test_google_factory_oauth_requires_project():
    with pytest.raises(ValueError, match="google_cloud_project"):
        get_provider("google", driver="gemini_api", auth_mode="oauth", google_access_token="token-only")


@pytest.mark.asyncio
async def test_build_provider_client_kwargs_async_google_oauth(db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="google",
        driver="gemini_api",
        display_name="Google Gemini",
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
            "oauth_identity_provider_id": "identity-1",
            "google_cloud_project": "demo-project",
        },
    )
    await db.commit()

    async def fake_build_google_access_token(_db, *, provider, get_secret_value_func):
        assert provider.name == "google"
        return ("ya29.token", "demo-project")

    monkeypatch.setattr(
        "app.services.control_plane_service.build_google_access_token",
        fake_build_google_access_token,
    )

    kwargs = await build_provider_client_kwargs_async(db, provider)
    assert kwargs["provider_name"] == "google"
    assert kwargs["auth_mode"] == "oauth"
    assert kwargs["google_access_token"] == "ya29.token"
    assert kwargs["google_project_id"] == "demo-project"
    assert "copilot_token" not in kwargs


@pytest.mark.asyncio
async def test_create_google_provider_stores_oauth_secret_without_api_key_ref(db):
    captured: list[tuple[str, str, str]] = []

    async def fake_set_secret_value(_db, *, tool_name, field_name, project_id, value):
        captured.append((tool_name, field_name, value))
        return type("SecretRef", (), {"id": "secret-id"})()

    payload = {
        "driver": "gemini_api",
        "display_name": "Google Gemini",
        "auth_mode": "oauth",
        "google_oauth_client_id": "client-id",
        "google_oauth_client_secret": "client-secret",
        "google_cloud_project": "demo-project",
        "is_global": True,
    }
    created = await create_provider(
        db,
        payload=payload,
        serialize_provider=lambda provider, model_count, active_count: {
            "id": provider.id,
            "name": provider.name,
            "auth_mode": provider.auth_mode,
        },
        set_secret_value_func=fake_set_secret_value,
    )

    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == created["id"]))).scalar_one()
    assert provider.auth_mode == "oauth"
    assert provider.api_key_secret_ref is None
    meta = await read_oauth_metadata(db, provider)
    assert meta["oauth_client_id"] == "client-id"
    assert meta["google_cloud_project"] == "demo-project"
    assert captured == [(f"control_plane_provider:{provider.id}", "google_oauth_client_secret", "client-secret")]


@pytest.mark.asyncio
async def test_update_google_provider_persists_config_and_secret(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="google",
        driver="gemini_api",
        display_name="Google Gemini",
        auth_mode="api_key",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    captured: list[tuple[str, str, str]] = []

    async def fake_set_secret_value(_db, *, tool_name, field_name, project_id, value):
        captured.append((tool_name, field_name, value))
        return type("SecretRef", (), {"id": "secret-id"})()

    await update_provider(
        db,
        provider_id=provider.id,
        payload={
            "auth_mode": "oauth",
            "google_oauth_client_id": "client-id-2",
            "google_oauth_client_secret": "client-secret-2",
            "google_cloud_project": "project-2",
        },
        serialize_provider=lambda current, model_count, active_count: {
            "id": current.id,
            "auth_mode": current.auth_mode,
        },
        set_secret_value_func=fake_set_secret_value,
    )

    refreshed = await db.get(LLMProvider, provider.id)
    assert refreshed is not None
    assert refreshed.auth_mode == "oauth"
    meta = await read_oauth_metadata(db, refreshed)
    assert meta["oauth_client_id"] == "client-id-2"
    assert meta["google_cloud_project"] == "project-2"
    assert captured == [(f"control_plane_provider:{provider.id}", "google_oauth_client_secret", "client-secret-2")]
