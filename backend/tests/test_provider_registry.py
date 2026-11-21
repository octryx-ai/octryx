"""The provider registry resolves exact driver ids only, refuses anything else, builds providers through their factories, and stores and resolves an openai-compatible endpoint and its secret."""

import uuid

import pytest

from app.agent.core.runtime.runtime_errors import ProviderRuntimeError
from app.agent.providers import (
    GoogleClient,
    OllamaClient,
    OpenAICompatibleClient,
    get_driver_spec,
    get_provider,
    infer_provider_runtime,
)
from app.models import LLMProvider
from app.services.admin.provider.admin_provider_service import create_provider
from app.services.control_plane_service import build_provider_client_kwargs_async
from app.services.secret import get_secret_value, set_secret_value

# MiniMax-shaped fixture: a generic URL + API-token vendor. Nothing here is
# hardcoded in the backend; it just exercises the openai_compatible driver.
MINIMAX_BASE_URL = "https://api.minimax.io/v1"


MINIMAX_MODEL_ID = "MiniMax-Text-01"


MINIMAX_API_TOKEN = "sk-minimax-test-token"


def test_infer_provider_runtime_resolves_the_driver_id():
    runtime = infer_provider_runtime(driver="gemini_api")

    assert runtime["name"] == "google"
    assert runtime["driver"] == "gemini_api"
    assert runtime["provider_family"] == "google"
    assert runtime["runtime_kind"] == "api"
    assert runtime["auth_mode"] == "api_key"


def test_provider_names_and_former_aliases_are_not_driver_ids():
    for value in ("google", "openrouter", "bedrock", "copilot", "openai", "custom", "litellm", "google_personal"):
        assert get_driver_spec(value) is None
        assert infer_provider_runtime(name=value, driver=None)["driver"] == ""


def test_get_provider_refuses_an_unknown_driver_explicitly():
    for driver in (None, "google", "claude_code_cli"):
        with pytest.raises(ProviderRuntimeError, match="Unknown provider driver") as exc_info:
            get_provider(provider_name="acceptance", driver=driver)
        assert exc_info.value.runtime_error_class == "permanent"


def test_openai_compatible_factory():
    client = get_provider(driver="openai_compatible", endpoint_url="http://localhost:8001/v1", api_key="test-key")

    assert isinstance(client, OpenAICompatibleClient)
    assert client.name == "openai_compatible"
    assert client.base_url == "http://localhost:8001/v1"


def test_ollama_factory():
    client = get_provider(driver="ollama", endpoint_url="http://localhost:11434")

    assert isinstance(client, OllamaClient)
    assert client.name == "ollama"


def test_gemini_factory():
    client = get_provider("google", driver="gemini_api", api_key="gemini-key", auth_mode="api_key")

    assert isinstance(client, GoogleClient)
    assert client.name == "google"


def test_openai_compatible_driver_spec_advertises_endpoint_requirement():
    spec = get_driver_spec("openai_compatible")

    assert spec is not None
    assert spec.requires_endpoint_url is True
    assert spec.config_hint


@pytest.mark.asyncio
async def test_admin_create_openai_compatible_stores_endpoint_and_secret_ref(db):
    provider_row: LLMProvider | None = None

    def _serialize(provider, model_count, active_count):
        nonlocal provider_row
        provider_row = provider
        return {"id": provider.id, "driver": provider.driver, "endpoint_url": provider.endpoint_url}

    created = await create_provider(
        db,
        payload={
            "driver": "openai_compatible",
            "display_name": "MiniMax",
            "endpoint_url": MINIMAX_BASE_URL,
            "api_key": MINIMAX_API_TOKEN,
            "is_global": True,
        },
        serialize_provider=_serialize,
        set_secret_value_func=set_secret_value,
    )

    assert created["driver"] == "openai_compatible"
    assert created["endpoint_url"] == MINIMAX_BASE_URL
    assert provider_row is not None
    # base_url is stored on the row via endpoint_url; the token is only a secret ref.
    assert provider_row.endpoint_url == MINIMAX_BASE_URL
    assert provider_row.api_key_secret_ref
    # No plaintext token is persisted anywhere on the provider row.
    assert not hasattr(provider_row, "api_key") or getattr(provider_row, "api_key", None) is None
    for value in vars(provider_row).values():
        assert value != MINIMAX_API_TOKEN
    # The referenced secret resolves back to the original token.
    resolved = await get_secret_value(db, secret_id=provider_row.api_key_secret_ref)
    assert resolved == MINIMAX_API_TOKEN


@pytest.mark.asyncio
async def test_build_client_kwargs_openai_compatible_resolves_base_url_and_key(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="minimax",
        provider_family="openai",
        driver="openai_compatible",
        runtime_kind="api",
        display_name="MiniMax",
        endpoint_url=MINIMAX_BASE_URL,
        auth_mode="api_key",
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
        value=MINIMAX_API_TOKEN,
    )
    provider.api_key_secret_ref = secret_entry.id
    await db.commit()

    kwargs = await build_provider_client_kwargs_async(db, provider)

    assert kwargs["driver"] == "openai_compatible"
    assert kwargs["endpoint_url"] == MINIMAX_BASE_URL
    assert kwargs["api_key"] == MINIMAX_API_TOKEN

    # The assembled kwargs construct a client whose base_url is the endpoint_url.
    client = get_provider(**kwargs)
    try:
        assert isinstance(client, OpenAICompatibleClient)
        assert client.base_url == MINIMAX_BASE_URL
    finally:
        await client.close()
