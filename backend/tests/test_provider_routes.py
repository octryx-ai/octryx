import uuid

import pytest
from sqlalchemy import select

from app.agent.core.runtime.runtime_errors import ProviderRuntimeError
from app.models import LLMModel, LLMProvider
from app.services import provider as provider_service
from app.services.secret import get_secret_value


@pytest.mark.asyncio
async def test_public_provider_create_and_list(client, auth_headers, db):
    create_resp = await client.post(
        "/api/v1/providers",
        headers=auth_headers,
        json={"name": "openrouter", "driver": "openrouter_api", "display_name": "OpenRouter Public", "api_key": "sk-public-create"},
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert "sk-public-create" not in str(created)
    assert "api_key" not in created
    assert "api_key_secret_ref" not in created
    assert created["name"] == "openrouter"
    assert created["display_name"] == "OpenRouter Public"
    assert created["model_count"] == 0

    provider = await db.get(LLMProvider, created["id"])
    assert provider is not None
    assert not hasattr(provider, "api_key")
    assert provider.api_key_secret_ref
    assert await get_secret_value(db, secret_id=provider.api_key_secret_ref) == "sk-public-create"

    list_resp = await client.get("/api/v1/providers", headers=auth_headers)
    assert list_resp.status_code == 200
    providers = list_resp.json()
    assert "sk-public-create" not in str(providers)
    assert "api_key_secret_ref" not in str(providers)
    assert any(item["id"] == created["id"] and item["model_count"] == 0 for item in providers)


@pytest.mark.asyncio
async def test_public_provider_model_sync_adds_missing_models(client, auth_headers, db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="OpenRouter",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_build_provider_client_kwargs_async(_db, _provider):
        return {"provider_name": "openrouter", "api_key": "test-key"}

    class FakeClient:
        async def list_models(self):
            return [
                {"id": "openai/gpt-4.1", "name": "GPT-4.1", "context_length": 128000},
                {"id": "openai/gpt-4.1", "name": "GPT-4.1", "context_length": 128000},
                {"id": "", "name": "ignore-me"},
            ]

        async def close(self):
            return None

    monkeypatch.setattr(
        "app.api.routes.providers.build_provider_client_kwargs_async",
        fake_build_provider_client_kwargs_async,
    )
    monkeypatch.setattr(provider_service, "get_provider_client", lambda **kwargs: FakeClient())

    resp = await client.post(f"/api/v1/providers/{provider.id}/models/sync", headers=auth_headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "synced"
    assert payload["sync_state"] == "success"
    assert payload["models_added"] == 1
    assert payload["models_seen"] == 2
    assert payload["models_ignored"] == 1

    models = (await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id))).scalars().all()
    assert len(models) == 1
    assert models[0].model_id == "openai/gpt-4.1"


@pytest.mark.asyncio
async def test_public_provider_model_sync_returns_no_models_state(client, auth_headers, db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="OpenRouter Empty",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_build_provider_client_kwargs_async(_db, _provider):
        return {"provider_name": "openrouter", "api_key": "test-key"}

    class FakeClient:
        async def list_models(self):
            return []

        async def close(self):
            return None

    monkeypatch.setattr(
        "app.api.routes.providers.build_provider_client_kwargs_async",
        fake_build_provider_client_kwargs_async,
    )
    monkeypatch.setattr(provider_service, "get_provider_client", lambda **kwargs: FakeClient())

    resp = await client.post(f"/api/v1/providers/{provider.id}/models/sync", headers=auth_headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "no_models"
    assert payload["sync_state"] == "no_models"
    assert payload["reason"] == "provider_returned_no_models"


@pytest.mark.asyncio
async def test_public_provider_model_sync_returns_structured_auth_failure(client, auth_headers, db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="OpenRouter Failure",
        is_global=True,
        is_active=True,
    )
    existing_model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="cached/model",
        display_name="Cached Model",
        is_active=True,
    )
    db.add_all([provider, existing_model])
    await db.commit()

    async def fake_build_provider_client_kwargs_async(_db, _provider):
        return {"provider_name": "openrouter", "api_key": "test-key"}

    class FakeClient:
        async def list_models(self):
            raise ProviderRuntimeError(
                "OpenRouter API error (401): unauthorized sk-secret-value", error_class="permanent", status_code=401
            )

        async def close(self):
            return None

    monkeypatch.setattr(
        "app.api.routes.providers.build_provider_client_kwargs_async",
        fake_build_provider_client_kwargs_async,
    )
    monkeypatch.setattr(provider_service, "get_provider_client", lambda **kwargs: FakeClient())

    resp = await client.post(f"/api/v1/providers/{provider.id}/models/sync", headers=auth_headers)
    assert resp.status_code == 401
    payload = resp.json()
    detail = payload["detail"]
    assert detail["sync_state"] == "stale_cache"
    assert detail["failure_state"] == "auth_denied"
    assert detail["cache_state"] == "stale_cache"
    assert detail["total_models"] == 1
    assert "sk-secret-value" not in str(payload)


@pytest.mark.asyncio
async def test_public_provider_model_sync_returns_404_for_missing_provider(client, auth_headers):
    missing_provider_id = str(uuid.uuid4())

    resp = await client.post(f"/api/v1/providers/{missing_provider_id}/models/sync", headers=auth_headers)

    assert resp.status_code == 404
    payload = resp.json()
    assert payload["detail"] == "Provider not found"
    assert payload["status_code"] == 404
    assert payload["error"] == "Provider not found"
    assert payload["request_id"]
