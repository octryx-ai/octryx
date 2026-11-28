"""Provider model limits, the runtime panel's model capabilities, context budget profiles and tool result compressors via the admin API."""

import uuid

import pytest

from app.models import LLMModel, LLMProvider
from app.services.control_plane_service import upsert_runtime_target


@pytest.mark.asyncio
async def test_provider_model_limits_can_be_updated_via_admin_api(admin_client, db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="OpenRouter",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="test/model",
        display_name="Test Model",
        context_length=128000,
        max_tokens_per_request=8000,
        pricing_input=3.0,
        pricing_output=15.0,
        supports_tools=True,
        supports_vision=False,
        is_active=True,
    )
    db.add(model)
    await db.commit()

    list_resp = await admin_client.get(f"/admin/chat/api/panel/providers/{provider.id}/models")
    assert list_resp.status_code == 200
    models = list_resp.json()
    assert models[0]["max_tokens_per_request"] == 8000
    assert models[0]["pricing_input"] == 3.0
    assert models[0]["pricing_output"] == 15.0

    update_resp = await admin_client.put(
        f"/admin/chat/api/panel/providers/{provider.id}/models/{model.id}",
        json={
            "max_tokens_per_request": 20000,
            "pricing_input": 4.5,
            "pricing_output": 18.75,
            "supports_tools": False,
            "supports_vision": True,
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["max_tokens_per_request"] == 20000
    assert update_resp.json()["pricing_input"] == 4.5
    assert update_resp.json()["pricing_output"] == 18.75
    assert update_resp.json()["supports_tools"] is False
    assert update_resp.json()["supports_vision"] is True

    clear_resp = await admin_client.put(
        f"/admin/chat/api/panel/providers/{provider.id}/models/{model.id}",
        json={"pricing_input": None, "pricing_output": None},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["pricing_input"] is None
    assert clear_resp.json()["pricing_output"] is None

    await db.refresh(model)
    refreshed = await db.get(LLMModel, model.id)
    assert refreshed is not None
    assert refreshed.max_tokens_per_request == 20000
    assert refreshed.pricing_input is None
    assert refreshed.pricing_output is None
    assert refreshed.supports_tools is False
    assert refreshed.supports_vision is True


@pytest.mark.asyncio
async def test_runtime_panel_exposes_model_capabilities(admin_client, db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="bedrock",
        driver="bedrock_api",
        display_name="Bedrock Runtime",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    db.add(
        LLMModel(
            id=str(uuid.uuid4()),
            provider_id=provider.id,
            model_id="amazon.nova-2-lite-v1:0",
            display_name="Nova 2 Lite",
            supports_tools=True,
            supports_vision=False,
            is_active=True,
        )
    )
    target = await upsert_runtime_target(
        db,
        provider=provider,
        model_id="amazon.nova-2-lite-v1:0",
        make_primary=True,
        is_active=True,
    )
    await db.commit()

    resp = await admin_client.get("/admin/chat/api/panel/runtimes")

    assert resp.status_code == 200
    runtime = next(row for row in resp.json() if row["id"] == target.id)
    assert runtime["supports_tools"] is True
    assert runtime["supports_vision"] is False




