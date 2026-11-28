"""U3: the admin model editor governs the prompt-cache rate pair (USD per million tokens)."""

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, LLMModel, LLMProvider


@pytest.mark.asyncio
async def test_admin_sets_clears_and_is_refused_cache_rates(admin_client, db):
    provider = LLMProvider(id=str(uuid.uuid4()), name="manual", display_name="Manual", is_global=True, is_active=True)
    db.add(provider)
    await db.flush()
    model = LLMModel(id=str(uuid.uuid4()), provider_id=provider.id, model_id="m", pricing_input=3.0, is_active=True)
    governed = LLMModel(
        id=str(uuid.uuid4()), provider_id=provider.id, model_id="g", cost_source="catalog_pricing", is_active=True
    )
    db.add_all([model, governed])
    await db.commit()
    url = f"/admin/chat/api/panel/providers/{provider.id}/models"

    saved = await admin_client.put(f"{url}/{model.id}", json={"pricing_cache_read": 0.3, "pricing_cache_write": 0})
    assert saved.status_code == 200
    assert (saved.json()["pricing_cache_read"], saved.json()["pricing_cache_write"]) == (0.3, 0.0)
    listed = {row["model_id"]: row for row in (await admin_client.get(url)).json()}
    assert (listed["m"]["pricing_cache_read"], listed["m"]["pricing_cache_write"]) == (0.3, 0.0)
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.provider.model.updated"))).scalar_one()
    assert audit.resource_id == model.id
    assert {"pricing_cache_read", "pricing_cache_write"} <= set(audit.details["changed_keys"])

    negative = await admin_client.put(f"{url}/{model.id}", json={"pricing_cache_read": -1, "pricing_cache_write": 1})
    assert negative.status_code == 422
    half = await admin_client.put(f"{url}/{model.id}", json={"pricing_cache_write": None})
    assert half.status_code == 400
    owned = await admin_client.put(f"{url}/{governed.id}", json={"pricing_cache_read": 1, "pricing_cache_write": 1})
    assert owned.status_code == 409

    cleared = await admin_client.put(f"{url}/{model.id}", json={"pricing_cache_read": None, "pricing_cache_write": None})
    assert cleared.status_code == 200
    await db.refresh(model)
    assert (model.pricing_cache_read, model.pricing_cache_write, model.pricing_input) == (None, None, 3.0)
