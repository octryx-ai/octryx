"""Only the gateway driver may declare a governed cost source, on the direct and the runtime path alike."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.budget import compute_usage_event_cost_attribution
from app.services.model_gateway.cost_contract import GOVERNED_COST_SOURCE_DRIVER
from tests.model_gateway.conftest import ALIAS, CATALOG_TURN_COST, stale_priced_gateway_model

UNGOVERNED_DRIVER = "openrouter_api"


def test_only_the_gateway_driver_key_carries_cost_source_authority() -> None:
    from app.agent.providers.litellm_gateway import PROVIDER_NAME
    from app.agent.providers.provider_registry import DRIVER_SPECS

    assert PROVIDER_NAME == GOVERNED_COST_SOURCE_DRIVER
    assert DRIVER_SPECS[GOVERNED_COST_SOURCE_DRIVER].driver == GOVERNED_COST_SOURCE_DRIVER
    assert UNGOVERNED_DRIVER != GOVERNED_COST_SOURCE_DRIVER


@pytest.mark.parametrize("driver", [UNGOVERNED_DRIVER, "", None, "LiteLLM Gateway"])
@pytest.mark.parametrize("declared_source", ["governed_free", "gateway_reported", "catalog_pricing"])
async def test_a_non_gateway_driver_cannot_self_declare_a_governed_cost_source(
    db, driver: str | None, declared_source: str
) -> None:
    await stale_priced_gateway_model(db)

    attribution = await compute_usage_event_cost_attribution(
        db,
        provider="litellm_gateway",
        driver=driver,
        model=ALIAS,
        tokens_in=1000,
        tokens_out=500,
        usage={
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "cost": 0.0,
            "cost_source": declared_source,
        },
    )

    assert attribution.cost == CATALOG_TURN_COST
    assert attribution.status == "priced"
    assert attribution.cost_source == ""


async def test_an_untrusted_declaration_does_not_change_a_provider_reported_charge(db) -> None:
    await stale_priced_gateway_model(db)

    attribution = await compute_usage_event_cost_attribution(
        db,
        provider="litellm_gateway",
        driver=UNGOVERNED_DRIVER,
        model=ALIAS,
        tokens_in=1000,
        tokens_out=500,
        usage={"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.42, "cost_source": "governed_free"},
    )

    assert attribution.cost == Decimal("0.420000")
    assert attribution.status == "provider_reported_cost"
    assert attribution.cost_source == ""


