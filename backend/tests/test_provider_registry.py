"""The provider registry resolves exact driver ids only, refuses anything else, and stores and resolves a gateway
endpoint and its virtual key as a Secret Reference."""

import uuid

import pytest

from app.agent.providers import get_driver_spec, get_provider, infer_provider_runtime
from app.agent.runtime.runtime_errors import ProviderRuntimeError
from app.models import LLMProvider
from app.services.admin.provider.admin_provider_service import create_provider
from app.services.control_plane_service import build_provider_client_kwargs_async
from app.services.secret import get_secret_value, set_secret_value
from tests.model_gateway.conftest import BASE_URL, gateway_config

VIRTUAL_KEY = "sk-gateway-test-token"


def test_infer_provider_runtime_resolves_the_driver_id():
    runtime = infer_provider_runtime(driver="litellm_gateway")

    assert runtime["name"] == "litellm_gateway"
    assert runtime["driver"] == "litellm_gateway"
    assert runtime["provider_family"] == "litellm"
    assert runtime["runtime_kind"] == "api"
    assert runtime["auth_mode"] == "api_key"


def test_provider_names_and_former_driver_ids_are_not_driver_ids():
    for value in ("google", "openrouter", "bedrock", "bedrock_api", "copilot_api", "gemini_api", "ollama",
                  "openai_compatible", "openai", "custom", "litellm"):
        assert get_driver_spec(value) is None
        assert infer_provider_runtime(name=value, driver=value)["driver"] == ""


def test_get_provider_refuses_an_unknown_driver_explicitly():
    for driver in (None, "google", "openai_compatible", "claude_code_cli"):
        with pytest.raises(ProviderRuntimeError, match="Unknown provider driver") as exc_info:
            get_provider(provider_name="acceptance", driver=driver)
        assert exc_info.value.runtime_error_class == "permanent"


def test_the_gateway_driver_spec_advertises_its_endpoint_requirement():
    spec = get_driver_spec("litellm_gateway")

    assert spec is not None
    assert spec.requires_endpoint_url is True
    assert spec.config_hint


@pytest.mark.asyncio
async def test_admin_create_stores_the_endpoint_and_only_a_secret_ref(db):
    provider_row: LLMProvider | None = None

    def _serialize(provider, model_count, active_count):
        nonlocal provider_row
        provider_row = provider
        return {"id": provider.id, "driver": provider.driver, "endpoint_url": provider.endpoint_url}

    created = await create_provider(
        db,
        payload={
            "driver": "litellm_gateway",
            "display_name": "Gateway",
            "endpoint_url": BASE_URL,
            "api_key": VIRTUAL_KEY,
            "config_json": gateway_config(),
            "is_global": True,
        },
        serialize_provider=_serialize,
        set_secret_value_func=set_secret_value,
    )

    assert created["driver"] == "litellm_gateway"
    assert created["endpoint_url"] == BASE_URL
    assert provider_row is not None
    assert provider_row.api_key_secret_ref
    for value in vars(provider_row).values():
        assert value != VIRTUAL_KEY
    resolved = await get_secret_value(db, secret_id=provider_row.api_key_secret_ref, purpose="test.read")
    assert resolved == VIRTUAL_KEY


@pytest.mark.asyncio
async def test_build_client_kwargs_resolves_the_endpoint_and_the_virtual_key(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="litellm_gateway",
        provider_family="litellm",
        driver="litellm_gateway",
        runtime_kind="api",
        display_name="Gateway",
        endpoint_url=BASE_URL,
        auth_mode="api_key",
        config_json=gateway_config(),
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    secret_entry = await set_secret_value(
        db,
        tool_name=f"control_plane_provider:{provider.id}",
        field_name="api_key",
        project_id=None,
        value=VIRTUAL_KEY,
    )
    provider.api_key_secret_ref = secret_entry.id
    await db.commit()

    kwargs = await build_provider_client_kwargs_async(db, provider)

    assert kwargs["driver"] == "litellm_gateway"
    assert kwargs["endpoint_url"] == BASE_URL
    assert kwargs["api_key"] == VIRTUAL_KEY
