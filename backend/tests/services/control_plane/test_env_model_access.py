"""The first start's model from the environment: ``LLM_PROVIDER`` + ``AGENT_DEFAULT_MODEL`` become one route of the
bundled LiteLLM and the platform default."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agent.providers.provider_registry import infer_provider_runtime
from app.agent.providers.sampling_capabilities import sampling_temperature
from app.models import LLMProvider
from app.services.control_plane.config import ensure_default_control_plane_provider
from app.services.control_plane.env_model_access import EnvModelAccess, env_model_access, env_model_access_problem
from app.services.model_gateway import bundled_litellm
from tests.services.models_and_providers.test_bundled_routes import litellm  # noqa: F401


def _settings(**overrides):
    base = {
        "llm_provider": "",
        "llm_api_key": None,
        "llm_endpoint_url": None,
        "openrouter_api_key": None,
        "aws_region": "eu-central-1",
        "agent_default_model": None,
    }
    return SimpleNamespace(**(base | overrides))


def test_no_provider_or_no_model_means_no_env_access():
    assert env_model_access(_settings()) is None
    assert env_model_access_problem(_settings()) == ""
    assert env_model_access(_settings(llm_provider="anthropic", llm_api_key="k")) is None


def test_an_unsupported_value_creates_nothing_and_says_what_works():
    settings = _settings(llm_provider="gemini", llm_api_key="sk-secret-xyz", agent_default_model="gemini-2.5")
    assert env_model_access(settings) is None
    problem = env_model_access_problem(settings)
    assert problem.startswith("LLM_PROVIDER=gemini is not supported")
    for name in ("anthropic", "openai", "bedrock", "openrouter", "Admin › Models"):
        assert name in problem
    assert "sk-secret-xyz" not in problem, "the start log never carries the key"
    assert env_model_access_problem(_settings(llm_provider="Bedrock")) == ""


def test_anthropic_takes_the_api_key():
    access = env_model_access(_settings(llm_provider="Anthropic", llm_api_key=" sk-ant-test ",
                                        agent_default_model="claude-sonnet-5"))
    assert access == EnvModelAccess("anthropic", "claude-sonnet-5", "claude-sonnet-5", {"api_key": "sk-ant-test"})


def test_openai_is_openai_compatible_only_with_an_endpoint():
    plain = env_model_access(_settings(llm_provider="openai", llm_api_key="k", agent_default_model="gpt-4.1"))
    assert (plain.provider_type, plain.credentials) == ("openai", {"api_key": "k"})
    compatible = env_model_access(_settings(llm_provider="OpenAI", llm_endpoint_url=" https://llm.example.org/v1 ",
                                            llm_api_key="k", agent_default_model="Qwen/Qwen3 32B"))
    assert compatible.provider_type == "openai_compatible"
    assert compatible.credentials == {"api_base": "https://llm.example.org/v1", "api_key": "k"}
    assert (compatible.model, compatible.alias) == ("Qwen/Qwen3 32B", "qwen-qwen3-32b")


def test_openrouter_prefers_its_own_key():
    own = env_model_access(_settings(llm_provider="openrouter", openrouter_api_key="or-key", llm_api_key="generic",
                                     agent_default_model="anthropic/claude-sonnet-5"))
    assert (own.provider_type, own.credentials) == ("openrouter", {"api_key": "or-key"})
    generic = env_model_access(_settings(llm_provider="openrouter", llm_api_key="generic", agent_default_model="m"))
    assert generic.credentials == {"api_key": "generic"}


def test_bedrock_takes_the_region_and_the_aws_keys_from_the_environment(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    settings = _settings(llm_provider="bedrock", aws_region="eu-west-1", agent_default_model="eu.anthropic.claude-sonnet-5")
    role = env_model_access(settings)
    assert (role.provider_type, role.credentials) == ("bedrock", {"aws_region_name": "eu-west-1"})

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    assert env_model_access(settings).credentials == {
        "aws_region_name": "eu-west-1", "aws_access_key_id": "AKIA-test", "aws_secret_access_key": "aws-secret"}

    monkeypatch.setenv("AWS_SESSION_TOKEN", "sso-session-token")
    assert env_model_access(settings).credentials["aws_session_token"] == "sso-session-token"


def test_claude_5_gets_no_explicit_temperature():
    assert sampling_temperature("claude-sonnet-5", 0) is None
    assert sampling_temperature("gpt-4.1", 0) == 0


async def _first_start(db, settings):
    return await ensure_default_control_plane_provider(db, settings=settings,
                                                       infer_provider_runtime_func=infer_provider_runtime)


@pytest.mark.asyncio
async def test_the_first_start_makes_the_model_a_bundled_route_and_the_default_once(db, litellm):  # noqa: F811
    settings = _settings(llm_provider="anthropic", llm_api_key="sk-ant-test", agent_default_model="claude-sonnet-5")

    provider = await _first_start(db, settings)
    again = await _first_start(db, settings)

    assert again.id == provider.id and provider.name == bundled_litellm.PROVIDER_NAME
    assert provider.default_model_id == "claude-sonnet-5"
    (route,) = litellm.models.values()
    assert route["model_name"] == "claude-sonnet-5"
    assert route["litellm_params"]["api_key"] == "sk-ant-test"
    assert "claude-sonnet-5" in provider.config_json["litellm_gateway"]["aliases"]
    rows = await db.execute(select(LLMProvider).where(LLMProvider.name == bundled_litellm.PROVIDER_NAME))
    assert len(list(rows.scalars())) == 1


@pytest.mark.asyncio
async def test_without_the_bundled_litellm_or_a_supported_value_nothing_is_created(db, monkeypatch):
    calls: list[object] = []

    async def no_bundled(_db):
        return None

    async def ensure_route(_db, access):
        calls.append(access)

    monkeypatch.setattr(bundled_litellm, "register_bundled_provider", no_bundled)
    monkeypatch.setattr("app.services.model_gateway.bundled_routes.ensure_route", ensure_route)

    assert await _first_start(db, _settings(llm_provider="anthropic", llm_api_key="k", agent_default_model="m")) is None
    assert await _first_start(db, _settings(llm_provider="gemini", agent_default_model="m")) is None
    assert calls == []
