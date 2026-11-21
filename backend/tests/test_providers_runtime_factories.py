"""Provider factories, missing credentials, the OpenRouter client and the refusal of a missing or unknown driver."""

import pytest

from app.agent.core.runtime.runtime_errors import ProviderRuntimeError
from app.agent.providers import BaseLLMProvider, BedrockClient, CopilotClient, OpenRouterClient, get_provider

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


def test_openrouter_factory():
    client = get_provider("openrouter", driver="openrouter_api", api_key="test-key")
    assert isinstance(client, OpenRouterClient)
    assert isinstance(client, BaseLLMProvider)
    assert client.name == "openrouter"


def test_bedrock_factory():
    client = get_provider("bedrock", driver="bedrock_api", region="us-east-1")
    assert isinstance(client, BedrockClient)
    assert isinstance(client, BaseLLMProvider)
    assert client.name == "bedrock"


def test_bedrock_factory_passes_prompt_caching_config():
    client = get_provider(
        "bedrock",
        driver="bedrock_api",
        region="us-east-1",
        config_json={"prompt_caching": {"enabled": True, "min_tokens": 1}},
    )

    assert isinstance(client, BedrockClient)
    assert client.config_json["prompt_caching"]["enabled"] is True


def test_bedrock_factory_passes_static_credentials():
    client = get_provider(
        "bedrock",
        driver="bedrock_api",
        region="eu-central-1",
        aws_access_key_id="access-key",
        aws_secret_access_key="secret-key",
        aws_session_token="session-token",
    )

    assert isinstance(client, BedrockClient)
    assert client.aws_access_key_id == "access-key"
    assert client.aws_secret_access_key == "secret-key"
    assert client.aws_session_token == "session-token"


def test_copilot_factory():
    client = get_provider("copilot", driver="copilot_api", copilot_token="test-token")
    assert isinstance(client, CopilotClient)
    assert isinstance(client, BaseLLMProvider)
    assert client.name == "copilot"
    assert client.access_token == "test-token"


def test_unknown_driver_is_refused():
    with pytest.raises(ProviderRuntimeError, match="Unknown provider driver"):
        get_provider("unknown", driver="unknown")


def test_openrouter_missing_key():
    with pytest.raises(ValueError, match="requires api_key"):
        get_provider("openrouter", driver="openrouter_api")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_openrouter_client_handles_empty_choices(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "stepfun/step-3.5-flash:free",
                "choices": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def post(self, path, content=None, headers=None):
            return FakeResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr("app.agent.providers.openrouter.httpx.AsyncClient", FakeAsyncClient)

    client = OpenRouterClient("test-key")
    result = await client.chat([{"role": "user", "content": "Reply with OK only."}])
    await client.close()

    assert result["content"] == ""
    assert result["tool_calls"] is None


def test_no_driver_has_no_default_provider():
    with pytest.raises(ProviderRuntimeError, match="Unknown provider driver"):
        get_provider(api_key="test-key")
