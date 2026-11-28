"""Shared helpers for the test_litellm_cost_authority_* modules."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import LLMModel, LLMProvider
from app.services.admin.provider import admin_provider_service
from tests.model_gateway.conftest import ALIAS, BASE_URL, VIRTUAL_KEY, FakeLiteLLMGateway, verified_admission


async def _sync(db, provider: LLMProvider, gateway: FakeLiteLLMGateway, config_json: dict[str, Any], monkeypatch):
    import app.agent.providers as providers_module
    from app.agent.providers.litellm_gateway import LiteLLMGatewayClient

    provider.config_json = config_json
    await db.flush()

    def _build_client(**_kwargs: Any) -> LiteLLMGatewayClient:
        return LiteLLMGatewayClient(
            endpoint_url=BASE_URL,
            api_key=VIRTUAL_KEY,
            config_json=config_json,
            transport=gateway.transport(),
            project_admission=verified_admission(ALIAS),
        )

    monkeypatch.setattr(providers_module, "get_provider", _build_client)

    async def _kwargs(_db, _provider) -> dict[str, Any]:
        return {}

    return await admin_provider_service.sync_provider_models(
        db,
        provider_id=provider.id,
        build_provider_client_kwargs_async_func=_kwargs,
    )


async def _synced_model(db, provider: LLMProvider) -> LLMModel:
    return (
        await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id, LLMModel.model_id == ALIAS))
    ).scalar_one()
