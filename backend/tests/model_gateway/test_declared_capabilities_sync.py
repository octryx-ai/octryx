"""A gateway alias's declared tools/vision win over the catalog probe.

llama.cpp's server advertises only "completion"; a sync that wrote ``supports_tools=false`` into the catalog row
would be mirrored into the alias by the next catalog save, and the gateway would refuse Codex's tool calls
(``capability_not_declared_for_alias``). The declaration stays; the probe's difference is a warning.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.models import LLMModel, LLMProvider
from app.services.admin.provider import admin_provider_service
from app.services.model_catalog.alias_mirror import alias_entries, mirror_into_alias

ALIAS = "local-coder"


def _gateway(capabilities: dict[str, Any] | None) -> LLMProvider:
    entry: dict[str, Any] = {"model_group": ALIAS, "context_limit": 128000, "data_policy_class": "internal",
                             "cost": {"source": "governed_free", "contract_reference": "flat-rate"}}
    if capabilities is not None:
        entry["capabilities"] = capabilities
    return LLMProvider(id=str(uuid.uuid4()), name=f"gw-{uuid.uuid4().hex[:6]}", display_name="Local gateway",
                       driver="litellm_gateway", provider_family="litellm", runtime_kind="api", auth_mode="api_key",
                       is_active=True, endpoint_url="http://127.0.0.1:8797/v1",
                       config_json={"litellm_gateway": {"aliases": {ALIAS: entry}}})


async def _sync(db, provider: LLMProvider, probe: dict[str, Any], monkeypatch) -> dict[str, Any]:
    import app.agent.providers as providers_module

    class _Probe:
        async def list_models(self) -> list[dict[str, Any]]:
            return [{"id": ALIAS, **probe}]

        async def close(self) -> None:
            return None

    monkeypatch.setattr(providers_module, "get_provider", lambda **_kwargs: _Probe())

    async def _kwargs(_db, _provider) -> dict[str, Any]:
        return {}

    return await admin_provider_service.sync_provider_models(db, provider_id=provider.id,
                                                             build_provider_client_kwargs_async_func=_kwargs)


async def _row(db, provider) -> LLMModel:
    return (await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id))).scalar_one()


@pytest.mark.asyncio
async def test_the_declared_tools_stay_and_the_probe_difference_is_a_warning(db, monkeypatch):
    provider = _gateway({"tools": True, "vision": False})
    db.add(provider)
    await db.commit()

    result = await _sync(db, provider, {"supports_tools": False, "supports_vision": False}, monkeypatch)
    row = await _row(db, provider)
    assert row.supports_tools is True
    assert result["capability_warnings"] == [
        {"model_id": ALIAS, "capability": "tools", "declared": True, "probe": False}]

    # a later catalog save mirrors the row into the alias: still tools=true
    row.capabilities_json = {"tools": False, "vision": False, "coding": False, "long_context": False}
    await db.commit()
    await _sync(db, provider, {"supports_tools": False}, monkeypatch)
    row = await _row(db, provider)
    assert row.capabilities_json["tools"] is True
    assert mirror_into_alias(provider, row)
    assert alias_entries(provider)[ALIAS]["capabilities"]["tools"] is True


@pytest.mark.asyncio
async def test_without_a_declaration_the_probe_applies_as_before(db, monkeypatch):
    provider = _gateway(None)
    db.add(provider)
    await db.commit()

    result = await _sync(db, provider, {"supports_tools": True}, monkeypatch)
    assert (await _row(db, provider)).supports_tools is True
    assert "capability_warnings" not in result
