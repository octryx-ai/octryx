"""The first start's model access from the environment: Bedrock, an Anthropic key or an OpenAI-compatible endpoint."""

from types import SimpleNamespace

import pytest

from app.agent.providers.provider_registry import infer_provider_runtime
from app.agent.providers.sampling_capabilities import sampling_temperature
from app.services.control_plane.config import ensure_default_control_plane_provider
from app.services.control_plane.env_model_access import (
    ANTHROPIC_OPENAI_COMPATIBLE_ENDPOINT,
    env_model_access,
    env_model_access_problem,
)
from app.services.control_plane.provider_auth import resolve_provider_api_key
from app.services.secret import get_secret_value


def _settings(**overrides):
    base = {
        "llm_provider": "",
        "llm_api_key": None,
        "llm_endpoint_url": None,
        "openrouter_api_key": None,
        "copilot_token": None,
        "aws_region": "eu-central-1",
        "aws_bedrock_role_arn": None,
        "agent_default_model": None,
    }
    return SimpleNamespace(**(base | overrides))


def test_no_provider_means_no_env_access():
    assert env_model_access(_settings()) is None
    assert env_model_access_problem(_settings()) == ""


def test_an_unsupported_value_creates_nothing_and_says_what_works():
    """LLM_PROVIDER=gemini (or a typo) must not become a provider without a driver that fails only on the first call."""
    settings = _settings(llm_provider="gemini", llm_api_key="sk-secret-xyz")
    assert env_model_access(settings) is None
    problem = env_model_access_problem(settings)
    assert problem.startswith("LLM_PROVIDER=gemini is not supported")
    for name in ("anthropic", "openai", "bedrock", "openrouter", "Admin › Models › Providers"):
        assert name in problem
    assert "sk-secret-xyz" not in problem, "the start log never carries the key"
    assert env_model_access_problem(_settings(llm_provider="Bedrock")) == ""
    assert env_model_access(_settings(llm_provider="openai_compatible", llm_endpoint_url="https://x/v1")).name == "openai"


def test_anthropic_key_goes_through_the_openai_compatible_endpoint():
    access = env_model_access(_settings(llm_provider="anthropic", llm_api_key="sk-ant-test"))
    assert access.name == "anthropic"
    assert access.driver == "openai_compatible"
    assert access.endpoint_url == ANTHROPIC_OPENAI_COMPATIBLE_ENDPOINT
    assert access.api_key == "sk-ant-test"


def test_openai_compatible_endpoint_keeps_the_given_url():
    access = env_model_access(
        _settings(llm_provider="OpenAI", llm_endpoint_url=" https://llm.example.org/v1 ", llm_api_key="k")
    )
    assert (access.name, access.driver, access.endpoint_url) == ("openai", "openai_compatible", "https://llm.example.org/v1")


def test_claude_5_gets_no_explicit_temperature_on_compatible_endpoints():
    assert sampling_temperature("claude-sonnet-5", 0) is None
    assert sampling_temperature("gpt-4.1", 0) == 0


@pytest.mark.asyncio
async def test_anthropic_bootstrap_creates_a_runnable_provider_with_a_stored_key(db):
    provider = await ensure_default_control_plane_provider(
        db,
        settings=_settings(
            llm_provider="anthropic", llm_api_key="sk-ant-test", agent_default_model="claude-sonnet-5"
        ),
        infer_provider_runtime_func=infer_provider_runtime,
    )
    assert provider.driver == "openai_compatible"
    assert provider.endpoint_url == ANTHROPIC_OPENAI_COMPATIBLE_ENDPOINT
    assert provider.display_name == "Anthropic (Default)"
    assert provider.default_model_id == "claude-sonnet-5"
    assert provider.api_key_secret_ref
    key = await resolve_provider_api_key(
        db, provider, settings=_settings(), get_secret_value_func=get_secret_value
    )
    assert key == "sk-ant-test"


@pytest.mark.asyncio
async def test_bedrock_bootstrap_uses_the_region_and_no_key(db):
    provider = await ensure_default_control_plane_provider(
        db,
        settings=_settings(llm_provider="bedrock", aws_region="eu-west-1"),
        infer_provider_runtime_func=infer_provider_runtime,
    )
    assert provider.driver == "bedrock_api"
    assert provider.aws_region == "eu-west-1"
    assert provider.api_key_secret_ref is None


@pytest.mark.asyncio
async def test_the_first_start_model_gets_its_list_price(db):
    from sqlalchemy import delete, select

    from app.models import ControlPlaneRuntimeTarget, LLMModel
    from app.services.budget.list_prices import list_price
    from app.services.control_plane.config import ensure_default_runtime_target
    from app.services.control_plane_service import (
        get_or_create_control_plane_config,
        get_runtime_targets,
        resequence_runtime_targets,
        sync_primary_runtime_target,
    )

    config = await get_or_create_control_plane_config(db)
    await db.execute(delete(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.config_id == config.id))
    config.provider_id, config.model_id = None, None
    await db.flush()
    settings = _settings(llm_provider="bedrock", agent_default_model="eu.anthropic.claude-sonnet-5")

    async def _bootstrap(session):
        return await ensure_default_control_plane_provider(
            session, settings=settings, infer_provider_runtime_func=infer_provider_runtime,
        )

    await ensure_default_runtime_target(
        db, config, get_runtime_targets_func=get_runtime_targets,
        resequence_runtime_targets_func=resequence_runtime_targets,
        sync_primary_runtime_target_func=sync_primary_runtime_target,
        ensure_default_control_plane_provider_func=_bootstrap,
    )
    row = (await db.execute(select(LLMModel).where(LLMModel.model_id == "eu.anthropic.claude-sonnet-5"))).scalar_one()
    expected = list_price("eu.anthropic.claude-sonnet-5")
    assert (row.pricing_input, row.pricing_output) == (expected.input, expected.output)
    assert row.cleared_up_to



def test_the_price_table_is_dated_and_sourced():
    import json
    from pathlib import Path

    table = json.loads((Path(__file__).resolve().parents[1] / "app/services/budget/list_prices.json").read_text())
    assert table["read_on"]
    assert all(entry["source"] and entry["input"] >= 0 and entry["output"] >= 0 for entry in table["models"].values())
