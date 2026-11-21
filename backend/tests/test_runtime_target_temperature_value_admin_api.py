"""The admin runtime API shows the temperature a target's client sends, from its model's catalog row.

A runtime target holds no temperature of its own: the value is set on the model catalog row (``LLMModel.temperature``)
and the target only overrides whether the model gets one (``temperature_support``; "rejects" = never send). A request
that still sends a per-target ``temperature`` is refused.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from tests.conftest import ADMIN_PASSWORD
from tests.runtime_target_temperature_value_support import ACCEPTING


async def _runtime_target(db, *, driver: str, name: str, model_id: str = ACCEPTING,
                          temperature: float | None = None) -> ControlPlaneRuntimeTarget:
    provider = LLMProvider(
        id=str(uuid.uuid4()), name=name, driver=driver, display_name=name, is_active=True, is_global=True
    )
    db.add(provider)
    db.add(LLMModel(provider_id=provider.id, model_id=model_id, display_name=model_id, is_active=True,
                    temperature=temperature))
    config = (await db.execute(select(ControlPlaneConfig))).scalars().first()
    target = ControlPlaneRuntimeTarget(
        id=str(uuid.uuid4()), config_id=config.id, provider_id=provider.id, model_id=model_id, priority=9
    )
    db.add(target)
    await db.commit()
    return target


async def _login(client) -> None:
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})).status_code == 303


async def test_the_runtime_row_shows_the_models_catalog_value_and_never_send(client, db):
    await _login(client)
    target = await _runtime_target(db, driver="bedrock_api", name="bedrock", temperature=0.7)
    url = f"/admin/chat/api/panel/runtimes/{target.id}"

    listed = {row["id"]: row for row in (await client.get("/admin/chat/api/panel/runtimes")).json()}
    row = listed[target.id]
    assert "temperature" not in row and "temperature_mode" not in row
    assert row["temperature_effective"] == {
        "mode": "sent", "value": 0.7, "reason": "model_value", "label": "0.7 (set for this model)"
    }

    body = (await client.put(url, json={"temperature_support": "rejects"})).json()
    assert body["accepts_temperature"] is False
    assert body["temperature_effective"]["reason"] == "target_never_send"

    body = (await client.put(url, json={"temperature_support": "catalog"})).json()
    assert body["accepts_temperature"] is None and body["temperature_effective"]["value"] == 0.7


@pytest.mark.parametrize("payload", [{"temperature": 0.7}, {"temperature": "never_send"}])
async def test_a_per_target_temperature_is_refused(client, db, payload):
    await _login(client)
    target = await _runtime_target(db, driver="bedrock_api", name="bedrock")
    response = await client.put(f"/admin/chat/api/panel/runtimes/{target.id}", json=payload)
    assert response.status_code == 422
    created = await client.post(
        "/admin/chat/api/panel/runtimes",
        json={"provider_id": target.provider_id, "model_id": "other-model", **payload},
    )
    assert created.status_code == 422
    await db.refresh(target)
    assert target.accepts_temperature is None
