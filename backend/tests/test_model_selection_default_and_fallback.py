"""Default & fallback: one platform order of catalog models, two fallback choices, task models."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.runtime.runtime_fallback_policy import (
    RUNTIME_FALLBACK_MODE_ALL_RUNTIMES,
    RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY,
)
from app.agent.engine.runtime._engine_runtime_retry_policy import build_runtime_retry_policy
from app.models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider, Project, SystemConfig, User
from app.services.auth import create_access_token
from app.services.model_selection.page import default_and_fallback_page
from app.services.model_selection.platform_order import ModelOrderError, order_models, save_order
from app.services.model_selection.task_models import TaskModelsError, load_task_models, save_task_models

ROUTE = "/api/v1/admin/model-selection"

pytestmark = pytest.mark.asyncio


async def _models(db, *names: str, enabled: bool = True) -> list[LLMModel]:
    provider = LLMProvider(name=f"p-{uuid.uuid4().hex[:6]}", driver="bedrock_api", display_name="Provider One",
                           is_active=True)
    db.add(provider)
    await db.flush()
    rows = [LLMModel(provider_id=provider.id, model_id=f"{name}-{uuid.uuid4().hex[:4]}", display_name=name,
                     is_active=enabled, cleared_up_to="internal") for name in names]
    db.add_all(rows)
    await db.commit()
    return rows


async def _admin_id(db) -> str:
    return (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()


async def test_saving_the_order_rewrites_only_the_targets_and_the_fallback(db):
    first, second, third = await _models(db, "Orion Large", "Orion Fast", "Vega Pro")
    admin = await _admin_id(db)

    await save_order(db, model_keys=[first.catalog_key, second.catalog_key], fallback="next", actor_id=admin)
    await db.commit()
    change = await save_order(db, model_keys=[third.catalog_key, first.catalog_key], fallback="stop", actor_id=admin)
    await db.commit()

    ordered = [model.catalog_key for _target, _provider, model in await order_models(db)]
    assert ordered == [third.catalog_key, first.catalog_key]
    assert change["before"] == {"order": [first.catalog_key, second.catalog_key], "fallback": "next"}
    inactive = (await db.execute(select(ControlPlaneRuntimeTarget).where(
        ControlPlaneRuntimeTarget.model_id == second.model_id))).scalar_one()
    assert inactive.is_active is False  # removed from the order: deactivated, never deleted
    stored = await db.get(SystemConfig, "agent.runtime_fallback_mode")
    assert stored.value == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY


async def test_the_order_refuses_unknown_disabled_duplicate_or_empty_models(db):
    (enabled,) = await _models(db, "Orion Large")
    (disabled,) = await _models(db, "Old", enabled=False)
    admin = await _admin_id(db)
    cases = [
        ([], "next", "model_order_empty"),
        ([enabled.catalog_key, enabled.catalog_key], "next", "model_order_invalid"),
        (["no-such-model"], "next", "model_order_unknown_model"),
        ([disabled.catalog_key], "next", "model_order_model_not_enabled"),
        ([enabled.catalog_key], "driver_default", "model_fallback_invalid"),
    ]
    for keys, fallback, code in cases:
        with pytest.raises(ModelOrderError) as refused:
            await save_order(db, model_keys=keys, fallback=fallback, actor_id=admin)
        assert refused.value.code == code


async def test_unset_fallback_means_next_allowed_for_every_driver():
    gateway = [{"driver": "litellm_gateway", "model": "a"}]
    direct = [{"driver": "bedrock_api", "model": "b"}]
    for chain in (gateway, direct):
        policy = build_runtime_retry_policy({}, runtimes=chain)
        assert (policy["fallback_mode"], policy["fallback_mode_source"]) == (RUNTIME_FALLBACK_MODE_ALL_RUNTIMES, "default")
    stop = build_runtime_retry_policy({"runtime_fallback_mode": "first_runtime_only"}, runtimes=gateway)
    assert stop["fallback_mode"] == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY


async def test_task_models_store_catalog_keys_and_count_workspace_overrides(db):
    fast, large, outside = await _models(db, "Orion Fast", "Orion Large", "Vega Pro")
    (disabled,) = await _models(db, "Old", enabled=False)
    admin = await _admin_id(db)
    await save_order(db, model_keys=[large.catalog_key, fast.catalog_key], fallback="next", actor_id=admin)
    db.add(Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True,
                   config={"model_task_overrides": {"summarize": large.catalog_key}}))
    await db.commit()

    await save_task_models(db, tasks={"summarize": fast.catalog_key, "extract": None}, actor_id=admin)
    await db.commit()
    page = await default_and_fallback_page(db)

    assert await load_task_models(db) == {"summarize": fast.catalog_key}
    summarize = next(task for task in page["tasks"] if task["key"] == "summarize")
    assert summarize["model_key"] == fast.catalog_key and summarize["workspace_overrides"] == 1
    assert next(task for task in page["tasks"] if task["key"] == "extract")["model_key"] is None
    for tasks, code in (({"unknown": fast.catalog_key}, "task_models_invalid"),
                        ({"memory": "no-such-model"}, "task_models_unknown_model"),
                        ({"memory": disabled.catalog_key}, "task_models_model_not_enabled"),
                        ({"memory": outside.catalog_key}, "task_models_model_not_in_order")):
        with pytest.raises(TaskModelsError) as refused:
            await save_task_models(db, tasks=tasks, actor_id=admin)
        assert refused.value.code == code


async def test_the_api_saves_order_and_tasks_for_platform_admins_only(client, db):
    first, second = (model.catalog_key for model in await _models(db, "Orion Large", "Orion Fast"))
    headers = {"Authorization": f"Bearer {create_access_token(await _admin_id(db))}"}

    saved = await client.put(f"{ROUTE}/order", json={"models": [second, first], "fallback": "next"}, headers=headers)
    refused = await client.put(f"{ROUTE}/order", json={"models": [], "fallback": "next"}, headers=headers)
    tasks = await client.put(f"{ROUTE}/tasks", json={"tasks": {"memory": first}}, headers=headers)  # in the order

    assert saved.status_code == 200
    assert [row["display_name"] for row in saved.json()["order"]][:2] == ["Orion Fast", "Orion Large"]
    assert saved.json()["fallback"] == "next"
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "model_order_empty"
    assert next(task for task in tasks.json()["tasks"] if task["key"] == "memory")["model_key"] == first
    assert (await client.get(ROUTE)).status_code == 401
