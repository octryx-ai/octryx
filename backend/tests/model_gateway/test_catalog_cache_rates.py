"""Prompt-cache rates travel from the alias cost contract to the model row and into usage accounting."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.models import LLMModel, LLMProvider
from app.services.budget import compute_usage_event_cost_attribution
from app.services.model_gateway.cost_contract import COST_CONTRACT_DENIAL_PRICING_INVALID
from app.services.model_gateway.cost_contract_pricing import resolve_cost_contract_pricing
from tests.model_gateway.conftest import (
    ALIAS,
    CATALOG_INPUT_PRICE,
    CATALOG_OUTPUT_PRICE,
    FakeLiteLLMGateway,
    gateway_config,
    gateway_provider,
)
from tests.model_gateway.litellm_cost_authority_support import _sync, _synced_model

CACHE_READ_PRICE = 0.1
CACHE_WRITE_PRICE = 1.25


def _config_with_cache_rates() -> dict[str, Any]:
    config = gateway_config()
    config["litellm_gateway"]["aliases"][ALIAS]["cost"] = {
        "source": "catalog_pricing",
        "input_per_million_usd": CATALOG_INPUT_PRICE,
        "output_per_million_usd": CATALOG_OUTPUT_PRICE,
        "cache_read_per_million_usd": CACHE_READ_PRICE,
        "cache_write_per_million_usd": CACHE_WRITE_PRICE,
    }
    return config


async def test_sync_persists_the_cache_pair_and_a_contract_without_it_clears_it(db, monkeypatch) -> None:
    provider = gateway_provider()
    db.add(provider)
    await db.commit()

    await _sync(db, provider, FakeLiteLLMGateway(), _config_with_cache_rates(), monkeypatch)
    model = await _synced_model(db, provider)
    assert (model.pricing_cache_read, model.pricing_cache_write) == (CACHE_READ_PRICE, CACHE_WRITE_PRICE)
    assert (model.pricing_input, model.pricing_output) == (CATALOG_INPUT_PRICE, CATALOG_OUTPUT_PRICE)

    await _sync(db, provider, FakeLiteLLMGateway(), gateway_config(), monkeypatch)
    model = await _synced_model(db, provider)
    assert (model.pricing_cache_read, model.pricing_cache_write) == (None, None)
    assert model.cost_source == "catalog_pricing"


@pytest.mark.parametrize(
    "cache_pair",
    [
        {"cache_read_per_million_usd": 0.1},
        {"cache_read_per_million_usd": 0.1, "cache_write_per_million_usd": 0.0},
        {"cache_read_per_million_usd": float("nan"), "cache_write_per_million_usd": 1.0},
    ],
)
def test_a_half_or_unbillable_cache_pair_fails_the_sync(cache_pair: dict[str, Any]) -> None:
    contract = {"source": "catalog_pricing", "input_per_million_usd": 1.0, "output_per_million_usd": 2.0, **cache_pair}

    with pytest.raises(ValueError, match=COST_CONTRACT_DENIAL_PRICING_INVALID):
        resolve_cost_contract_pricing(contract)


async def _priced_model(db, *, cache_read: float | None, cache_write: float | None) -> str:
    provider = LLMProvider(id=str(uuid.uuid4()), name=f"claude-code-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add_all(
        [
            provider,
            LLMModel(
                id=str(uuid.uuid4()),
                provider_id=provider.id,
                model_id=ALIAS,
                pricing_input=CATALOG_INPUT_PRICE,
                pricing_output=CATALOG_OUTPUT_PRICE,
                pricing_cache_read=cache_read,
                pricing_cache_write=cache_write,
                is_active=True,
            ),
        ]
    )
    await db.commit()
    return provider.name


@pytest.mark.parametrize(
    ("cache_read", "cache_write", "expected_cost", "expected_status"),
    [
        # 1000 in * 1.0 + 500 out * 2.0 + 2000 read * 0.1 + 100 write * 1.25, per million.
        (CACHE_READ_PRICE, CACHE_WRITE_PRICE, Decimal("0.002325"), "priced_cache_rates"),
        # Without own cache rates the cache tokens are charged at the input rate, like the gateway and
        # Bedrock: (1000 + 2000 + 100) in * 1.0 + 500 out * 2.0, per million.
        (None, None, Decimal("0.004100"), "priced_cache_input_rate"),
    ],
)
async def test_usage_event_cache_tokens_are_charged_at_the_model_cache_rates(
    db, cache_read: float | None, cache_write: float | None, expected_cost: Decimal, expected_status: str
) -> None:
    provider_name = await _priced_model(db, cache_read=cache_read, cache_write=cache_write)

    attribution = await compute_usage_event_cost_attribution(
        db,
        provider=provider_name,
        model=ALIAS,
        tokens_in=1000,
        tokens_out=500,
        usage={},
        cache_read_tokens=2000,
        cache_creation_tokens=100,
    )

    assert attribution.status == expected_status
    assert attribution.cost == expected_cost
