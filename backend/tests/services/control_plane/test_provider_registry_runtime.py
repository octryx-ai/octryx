"""Created providers store their runtime metadata, client kwargs expose it, and control plane runtimes take the
provider's timeout and the model's token limit."""

import uuid

import pytest

from app.models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from app.services.admin.provider.admin_provider_service import create_provider
from app.services.control_plane_service import (
    build_provider_client_kwargs_async,
    get_or_create_control_plane_config,
    resolve_control_plane_runtimes,
)
from tests.model_gateway.conftest import ALIAS, BASE_URL, gateway_config, gateway_provider


@pytest.mark.asyncio
async def test_create_provider_stores_runtime_metadata(db):
    provider_row: LLMProvider | None = None

    def _serialize(provider, model_count, active_count):
        nonlocal provider_row
        provider_row = provider
        return {"id": provider.id, "driver": provider.driver, "runtime_kind": provider.runtime_kind,
                "endpoint_url": provider.endpoint_url}

    created = await create_provider(
        db,
        payload={"driver": "litellm_gateway", "display_name": "Gateway", "endpoint_url": BASE_URL,
                 "config_json": gateway_config(), "is_global": True},
        serialize_provider=_serialize,
    )

    assert created == {"id": provider_row.id, "driver": "litellm_gateway", "runtime_kind": "api",
                       "endpoint_url": BASE_URL}
    assert provider_row.provider_family == "litellm"


@pytest.mark.asyncio
async def test_build_provider_client_kwargs_async_exposes_driver_metadata(db):
    provider = gateway_provider(is_global=True, api_key_secret_ref=None)
    db.add(provider)
    await db.commit()

    kwargs = await build_provider_client_kwargs_async(db, provider)

    assert kwargs["provider_name"] == "litellm_gateway"
    assert kwargs["driver"] == "litellm_gateway"
    assert kwargs["provider_family"] == "litellm"
    assert kwargs["runtime_kind"] == "api"
    assert kwargs["endpoint_url"] == BASE_URL
    assert kwargs["config_json"] == gateway_config()
    assert kwargs["api_key"] is None


@pytest.mark.asyncio
async def test_resolve_control_plane_runtimes_applies_the_provider_timeout_and_the_model_token_limit(db):
    provider = gateway_provider(
        config_json={**gateway_config(), "request_timeout_seconds": 180},
        default_model_id=ALIAS,
        is_global=True,
    )
    db.add(provider)
    await db.flush()

    config = await get_or_create_control_plane_config(db)
    config.model_id = ALIAS
    config.provider_id = provider.id
    config.is_active = True
    db.add(LLMModel(id=str(uuid.uuid4()), provider_id=provider.id, model_id=ALIAS, display_name=ALIAS,
                    supports_tools=True, supports_streaming=True, max_tokens_per_request=512, is_active=True))
    db.add(ControlPlaneRuntimeTarget(id=str(uuid.uuid4()), config_id=config.id, provider_id=provider.id,
                                     model_id=ALIAS, priority=1, is_active=True))
    await db.commit()

    runtimes = await resolve_control_plane_runtimes(db)
    runtime = next(runtime for runtime in runtimes if runtime["provider_id"] == provider.id)

    assert runtime["request_timeout_seconds"] == 180
    assert runtime["max_tokens_per_request"] == 512
    assert runtime["supports_tools"] is True
    assert runtime["supports_vision"] is False
