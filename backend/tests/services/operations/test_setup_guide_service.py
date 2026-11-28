"""The setup guide starts with "Model ready", ends with the Workspaces and counts the active providers."""

import uuid

import pytest
from sqlalchemy import func, select

from app.models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from app.services.control_plane_service import get_or_create_control_plane_config
from app.services.setup_guide import get_setup_guide_status
from app.time_utils import utc_now
from tests.model_gateway.conftest import ALIAS, gateway_provider


@pytest.mark.asyncio
async def test_setup_guide_orders_model_ready_first_and_workspaces_last(db):
    status = await get_setup_guide_status(db)

    keys = [step["key"] for step in status["steps"]]
    assert keys[0] == "provider" and keys[-1] == "workspaces"
    assert status["steps"][0]["title"] == "Model ready"
    assert {"models", "default"} <= set(keys)
    assert "local_anchor" not in keys


@pytest.mark.asyncio
async def test_setup_guide_counts_active_providers(db):
    config = await get_or_create_control_plane_config(db)
    baseline_api = (await db.execute(select(func.count(LLMProvider.id)).where(
        LLMProvider.is_active, LLMProvider.runtime_kind == "api"))).scalar_one()

    provider = gateway_provider(display_name="Hosted API", is_global=True, health_status="ok",
                                last_health_check_at=utc_now())
    db.add(provider)
    await db.flush()
    db.add(LLMModel(id=str(uuid.uuid4()), provider_id=provider.id, model_id=ALIAS, display_name=ALIAS,
                    supports_tools=True, supports_streaming=True, is_active=True, last_synced_at=utc_now()))
    # The model before the target: a target's insert listener adds a catalog row when none exists yet.
    await db.flush()
    db.add(ControlPlaneRuntimeTarget(id=str(uuid.uuid4()), config_id=config.id, provider_id=provider.id,
                                     model_id=ALIAS, priority=1, is_active=True))
    await db.commit()

    status = await get_setup_guide_status(db)
    by_key = {step["key"]: step for step in status["steps"]}

    assert status["stats"]["api_provider_count"] == baseline_api + 1
    total_active = (await db.execute(select(func.count(LLMProvider.id)).where(LLMProvider.is_active))).scalar_one()
    assert status["stats"]["active_provider_count"] == total_active
    assert status["stats"]["active_runtime_count"] >= 1
    assert by_key["provider"]["status"] == "completed" and "Hosted API" in by_key["provider"]["detail"]
