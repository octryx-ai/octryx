"""A non-gateway catalog cannot declare a governed cost contract: it keeps its own pricing block and the sync reads cost contracts only for the gateway driver."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.models import LLMModel, LLMProvider
from app.services.admin.provider import admin_provider_service
from app.services.model_gateway.cost_contract import COST_CONTRACT_PAYLOAD_KEY
from app.services.model_gateway.cost_contract_pricing import resolve_model_pricing_update
from tests.model_gateway.conftest import ALIAS
from tests.model_gateway.litellm_cost_authority_support import _synced_model

# --- only the gateway driver's catalog may declare a contract -----------------

# An upstream ``/models`` entry as a non-gateway provider returns it, with a
# governed-looking ``cost_contract`` bolted on. Each case is a price the upstream
# must not be able to set: clear the row, zero the row, or reprice the row.
POISONED_CATALOG_CONTRACTS: tuple[dict[str, Any], ...] = (
    {"source": "gateway_reported", "contract_reference": "made-up"},
    {"source": "governed_free", "contract_reference": "made-up"},
    {"source": "catalog_pricing", "input_per_million_usd": 99.0, "output_per_million_usd": 99.0},
    # A malformed one too: it must not fail this provider's sync either, because
    # on an untrusted driver the key is never read at all.
    {"source": "free_because_i_said_so"},
)


# The operator-set prices on the non-gateway model row, which no upstream payload
# may touch.
OPERATOR_INPUT_PRICE = 5.0


OPERATOR_OUTPUT_PRICE = 9.0


def _impostor_provider() -> LLMProvider:
    """A provider *named* ``litellm_gateway`` but served by the OpenRouter driver.

    The name is operator-chosen, so it carries no authority. If sync trusted it,
    this provider's upstream ``/models`` response could clear or rewrite its own
    prices and stamp itself with a governed cost source.
    """

    return LLMProvider(
        id=str(uuid.uuid4()),
        name="litellm_gateway",
        display_name="LiteLLM Gateway",
        driver="openrouter_api",
        provider_family="openrouter",
        runtime_kind="api",
        auth_mode="api_key",
        is_active=True,
        endpoint_url="https://openrouter.test/api/v1",
    )


async def _sync_upstream_catalog(db, provider: LLMProvider, entry: dict[str, Any], monkeypatch) -> dict[str, Any]:
    """Run the real model sync over one upstream catalog entry from a fake client."""

    import app.agent.providers as providers_module

    class _UpstreamClient:
        async def list_models(self) -> list[dict[str, Any]]:
            return [entry]

        async def close(self) -> None:
            return None

    monkeypatch.setattr(providers_module, "get_provider", lambda **_kwargs: _UpstreamClient())

    async def _kwargs(_db, _provider) -> dict[str, Any]:
        return {}

    return await admin_provider_service.sync_provider_models(
        db,
        provider_id=provider.id,
        build_provider_client_kwargs_async_func=_kwargs,
    )


@pytest.fixture
async def priced_impostor_provider(db):
    """A non-gateway provider whose model row already carries operator prices."""

    provider = _impostor_provider()
    db.add_all(
        [
            provider,
            LLMModel(
                id=str(uuid.uuid4()),
                provider_id=provider.id,
                model_id=ALIAS,
                display_name=ALIAS,
                pricing_input=OPERATOR_INPUT_PRICE,
                pricing_output=OPERATOR_OUTPUT_PRICE,
                is_active=True,
            ),
        ]
    )
    await db.commit()
    return provider


@pytest.mark.parametrize("poisoned_contract", POISONED_CATALOG_CONTRACTS)
async def test_a_non_gateway_catalog_cannot_declare_a_governed_cost_contract(
    db, priced_impostor_provider, poisoned_contract: dict[str, Any], monkeypatch
) -> None:
    """An upstream ``/models`` payload may not own a price it does not govern.

    Only the gateway driver builds its catalog from an admitted alias contract;
    every other driver hands back whatever its upstream endpoint sent. So a
    ``cost_contract`` from a non-gateway provider is ignored outright: it can
    neither clear the operator's prices, nor zero them, nor reprice them, nor
    stamp ``llm_models.cost_source``.
    """

    result = await _sync_upstream_catalog(
        db,
        priced_impostor_provider,
        {"id": ALIAS, COST_CONTRACT_PAYLOAD_KEY: poisoned_contract},
        monkeypatch,
    )

    assert result["status"] == "synced"
    model = await _synced_model(db, priced_impostor_provider)
    assert (model.pricing_input, model.pricing_output) == (OPERATOR_INPUT_PRICE, OPERATOR_OUTPUT_PRICE)
    assert model.cost_source is None


async def test_a_non_gateway_catalog_applies_its_own_pricing_block(db, priced_impostor_provider, monkeypatch) -> None:
    """Ignoring ``cost_contract`` is not ignoring the payload: the catalog's own pricing block applies."""

    await _sync_upstream_catalog(
        db,
        priced_impostor_provider,
        {
            "id": ALIAS,
            "pricing": {"prompt": "0.000003", "completion": "0.000006"},
            COST_CONTRACT_PAYLOAD_KEY: {"source": "governed_free"},
        },
        monkeypatch,
    )

    model = await _synced_model(db, priced_impostor_provider)
    assert (model.pricing_input, model.pricing_output) == (3.0, 6.0)
    assert model.cost_source is None


@pytest.mark.parametrize("poisoned_contract", POISONED_CATALOG_CONTRACTS)
def test_the_sync_decision_reads_a_cost_contract_only_for_the_gateway_driver(
    poisoned_contract: dict[str, Any],
) -> None:
    """The same decision at unit level, over the closed set of driver values."""

    payload = {"id": ALIAS, COST_CONTRACT_PAYLOAD_KEY: poisoned_contract}

    for untrusted_driver in ("openrouter_api", "bedrock_api", "", None, "LiteLLM Gateway"):
        update = resolve_model_pricing_update(payload, driver=untrusted_driver)
        assert update.authoritative is False
        assert update.cost_source is None
        assert (update.pricing_input, update.pricing_output) == (None, None)
