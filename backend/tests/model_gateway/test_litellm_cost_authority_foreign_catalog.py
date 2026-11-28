"""A non-gateway catalog cannot declare a governed cost contract: the sync reads cost contracts only for the gateway driver."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.model_gateway.cost_contract import COST_CONTRACT_PAYLOAD_KEY
from app.services.model_gateway.cost_contract_pricing import resolve_model_pricing_update
from tests.model_gateway.conftest import ALIAS

# An upstream ``/models`` entry with a governed-looking ``cost_contract`` bolted on. Each case is a price a
# non-gateway catalog must not be able to set: clear the row, zero the row, or reprice the row.
POISONED_CATALOG_CONTRACTS: tuple[dict[str, Any], ...] = (
    {"source": "gateway_reported", "contract_reference": "made-up"},
    {"source": "governed_free", "contract_reference": "made-up"},
    {"source": "catalog_pricing", "input_per_million_usd": 99.0, "output_per_million_usd": 99.0},
    # On an untrusted driver the key is never read, so a malformed one is ignored too.
    {"source": "free_because_i_said_so"},
)


@pytest.mark.parametrize("poisoned_contract", POISONED_CATALOG_CONTRACTS)
def test_the_sync_decision_reads_a_cost_contract_only_for_the_gateway_driver(
    poisoned_contract: dict[str, Any],
) -> None:
    payload = {"id": ALIAS, COST_CONTRACT_PAYLOAD_KEY: poisoned_contract}

    for untrusted_driver in ("openrouter_api", "bedrock_api", "", None, "LiteLLM Gateway"):
        update = resolve_model_pricing_update(payload, driver=untrusted_driver)
        assert update.authoritative is False
        assert update.cost_source is None
        assert (update.pricing_input, update.pricing_output) == (None, None)
