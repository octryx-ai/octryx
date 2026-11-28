"""DB-backed default models: a new control plane names none, the configured model wins, and the first start's
environment model becomes the first runtime target with its list price."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.agent.providers.provider_registry import infer_provider_runtime
from app.models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from app.services.budget.list_prices import list_price
from app.services.control_plane import config as control_plane_config
from app.services.control_plane.config import (
    ensure_default_control_plane_provider,
)
from app.services.control_plane_service import (
    ensure_default_runtime_target,
    get_or_create_control_plane_config,
    get_runtime_targets,
    resequence_runtime_targets,
    sync_primary_runtime_target,
)
from app.services.model_gateway import bundled_litellm
from tests.model_gateway.conftest import gateway_provider
from tests.services.models_and_providers.test_bundled_routes import litellm  # noqa: F401


async def _delete_runtime_targets_and_configs(db) -> None:
    await db.execute(delete(ControlPlaneRuntimeTarget))
    await db.execute(delete(ControlPlaneConfig))
    await db.flush()


@pytest.mark.asyncio
async def test_a_new_control_plane_config_without_runtime_targets_names_no_model(db):
    await _delete_runtime_targets_and_configs(db)
    await db.commit()

    config = await get_or_create_control_plane_config(db)

    assert not config.model_id


@pytest.mark.asyncio
async def test_control_plane_default_runtime_target_prefers_db_config_model(db):
    await _delete_runtime_targets_and_configs(db)
    provider = gateway_provider(display_name="Default Provider", default_model_id="provider-model", is_global=True)
    config = ControlPlaneConfig(id=str(uuid.uuid4()), name="default", provider_id=provider.id, model_id="db-model",
                                is_active=True)
    db.add(provider)
    db.add(config)
    await db.commit()

    await ensure_default_runtime_target(db, config)
    await db.commit()

    target = (
        await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.config_id == config.id))
    ).scalar_one()
    assert target.model_id == "db-model"


@pytest.mark.asyncio
async def test_the_first_start_model_is_the_first_runtime_target_with_its_list_price(db, litellm):  # noqa: F811
    model_id = "eu.anthropic.claude-sonnet-5"
    config = await get_or_create_control_plane_config(db)
    await db.execute(delete(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.config_id == config.id))
    config.provider_id, config.model_id = None, None
    await db.flush()
    settings = SimpleNamespace(llm_provider="bedrock", llm_api_key=None, llm_endpoint_url=None,
                               openrouter_api_key=None, aws_region="eu-central-1", agent_default_model=model_id)

    async def _bootstrap(session):
        return await ensure_default_control_plane_provider(
            session, settings=settings, infer_provider_runtime_func=infer_provider_runtime,
        )

    await control_plane_config.ensure_default_runtime_target(
        db, config, get_runtime_targets_func=get_runtime_targets,
        resequence_runtime_targets_func=resequence_runtime_targets,
        sync_primary_runtime_target_func=sync_primary_runtime_target,
        ensure_default_control_plane_provider_func=_bootstrap,
    )

    (target,) = await get_runtime_targets(db, config)
    assert (target.model_id, target.priority) == (model_id, 1)
    row = (await db.execute(select(LLMModel).where(
        LLMModel.provider_id == target.provider_id, LLMModel.model_id == model_id))).scalar_one()
    expected = list_price(model_id)
    assert (row.pricing_input, row.pricing_output) == (expected.input, expected.output)
    assert row.cleared_up_to
    provider = await db.get(LLMProvider, target.provider_id)
    assert provider.name == bundled_litellm.PROVIDER_NAME


def test_the_price_table_is_dated_and_sourced():
    import json
    from pathlib import Path

    table = json.loads((Path(__file__).resolve().parents[3] / "app/services/budget/list_prices.json").read_text())
    assert table["read_on"]
    assert all(entry["source"] and entry["input"] >= 0 and entry["output"] >= 0 for entry in table["models"].values())
