"""The alias cost contract is authoritative for model-catalog sync.

An alias declares who owns its price. This suite walks one alias through every
cost-mode transition and asserts what model sync persists, because the defect it
pins down starts here: a ``catalog_pricing`` price that survives a move to
``governed_free`` or ``gateway_reported`` and is then billed to a call that mode
no longer prices. What the other end — usage accounting — does with the same
contract is ``test_litellm_cost_attribution``.

Everything runs against the offline fake gateway from ``conftest``; no cluster,
no network, no AWS.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.services.admin.provider import _admin_provider_models
from app.services.model_gateway.cost_contract import (
    COST_CONTRACT_PAYLOAD_KEY,
    GOVERNED_COST_SOURCE_DRIVER,
)
from app.services.model_gateway.cost_contract_pricing import resolve_model_pricing_update
from app.services.model_gateway.litellm.alias_catalog import (
    ALIAS_DENIAL_COST_PRICING_INVALID,
    ALIAS_DENIAL_COST_PRICING_NOT_BILLABLE,
    resolve_alias_admission,
)
from tests.model_gateway.conftest import (
    ALIAS,
    CATALOG_INPUT_PRICE,
    CATALOG_OUTPUT_PRICE,
    GATEWAY_REPORTED_COST,
    GOVERNED_FREE_COST,
    FakeLiteLLMGateway,
    alias_with_cost,
    gateway_config,
    gateway_provider,
)
from tests.model_gateway.litellm_cost_authority_support import _sync, _synced_model

CATALOG_PRICING_CONTRACT = {
    "source": "catalog_pricing",
    "input_per_million_usd": 1.0,
    "output_per_million_usd": 2.0,
}


@pytest.fixture
async def synced_gateway_provider(db, monkeypatch):
    """A gateway provider whose alias has already synced as ``catalog_pricing``.

    Every transition test starts from here, so "the old price is still there"
    is a real starting state rather than a fixture constant.
    """

    provider = gateway_provider()
    db.add(provider)
    await db.commit()
    await _sync(db, provider, FakeLiteLLMGateway(), gateway_config(), monkeypatch)
    model = await _synced_model(db, provider)
    assert (model.pricing_input, model.pricing_output) == (CATALOG_INPUT_PRICE, CATALOG_OUTPUT_PRICE)
    assert model.cost_source == "catalog_pricing"
    return provider


# --- what a governed catalog price must be ------------------------------------

_NAN = float("nan")


_INFINITY = float("inf")


# Every per-token rate a governed ``catalog_pricing`` contract must refuse, in
# either direction, with the fixed code it earns. Each rate is checked on its own (a
# positive sum can hide a zero rate); NaN and infinity are refused too, since both
# survive a naive ``> 0`` test on the cost they then produce.
UNUSABLE_CATALOG_RATES: tuple[tuple[Any, Any, str], ...] = (
    (0.0, 2.0, ALIAS_DENIAL_COST_PRICING_NOT_BILLABLE),
    (1.0, 0.0, ALIAS_DENIAL_COST_PRICING_NOT_BILLABLE),
    (0.0, 0.0, ALIAS_DENIAL_COST_PRICING_NOT_BILLABLE),
    (_NAN, 2.0, ALIAS_DENIAL_COST_PRICING_INVALID),
    (1.0, _NAN, ALIAS_DENIAL_COST_PRICING_INVALID),
    (_INFINITY, 2.0, ALIAS_DENIAL_COST_PRICING_INVALID),
    (1.0, _INFINITY, ALIAS_DENIAL_COST_PRICING_INVALID),
    (-1.0, 2.0, ALIAS_DENIAL_COST_PRICING_INVALID),
    ("1.0", 2.0, ALIAS_DENIAL_COST_PRICING_INVALID),
)


def _catalog_pricing_cost(input_rate: Any, output_rate: Any) -> dict[str, Any]:
    return {
        "source": "catalog_pricing",
        "input_per_million_usd": input_rate,
        "output_per_million_usd": output_rate,
    }


# --- published contract -------------------------------------------------------


@pytest.mark.parametrize(
    ("cost", "expected_contract"),
    [
        (None, CATALOG_PRICING_CONTRACT),
        (GOVERNED_FREE_COST, {"source": "governed_free"}),
        (GATEWAY_REPORTED_COST, {"source": "gateway_reported"}),
    ],
)
async def test_every_alias_publishes_its_cost_contract_to_model_sync(
    build_gateway_client,
    cost: dict[str, Any] | None,
    expected_contract: dict[str, Any],
) -> None:
    """A mode without a price still says so; silence is what let stale prices survive."""

    config = gateway_config() if cost is None else alias_with_cost(cost)
    client = build_gateway_client(FakeLiteLLMGateway(), config_json=config)

    catalog = await client.list_models()

    assert catalog[0][COST_CONTRACT_PAYLOAD_KEY] == expected_contract
    # The governance reference is closed call evidence, not catalog payload.
    assert "contract_reference" not in catalog[0][COST_CONTRACT_PAYLOAD_KEY]


# --- catalog sync transitions -------------------------------------------------


async def test_transition_to_governed_free_clears_the_price_and_records_the_audited_zero(
    db, synced_gateway_provider, monkeypatch
) -> None:
    await _sync(
        db,
        synced_gateway_provider,
        FakeLiteLLMGateway(),
        alias_with_cost(GOVERNED_FREE_COST),
        monkeypatch,
    )

    model = await _synced_model(db, synced_gateway_provider)
    assert model.pricing_input == 0.0
    assert model.pricing_output == 0.0
    assert model.cost_source == "governed_free"


async def test_transition_to_gateway_reported_cannot_leave_the_old_catalog_price_behind(
    db, synced_gateway_provider, monkeypatch
) -> None:
    await _sync(
        db,
        synced_gateway_provider,
        FakeLiteLLMGateway(),
        alias_with_cost(GATEWAY_REPORTED_COST),
        monkeypatch,
    )

    model = await _synced_model(db, synced_gateway_provider)
    assert model.pricing_input is None
    assert model.pricing_output is None
    assert model.cost_source == "gateway_reported"


async def test_catalog_pricing_keeps_synchronizing_its_positive_per_token_prices(
    db, synced_gateway_provider, monkeypatch
) -> None:
    repriced = gateway_config()
    repriced["litellm_gateway"]["aliases"][ALIAS]["cost"] = {
        "source": "catalog_pricing",
        "input_per_million_usd": 3.5,
        "output_per_million_usd": 7.25,
    }

    await _sync(db, synced_gateway_provider, FakeLiteLLMGateway(), repriced, monkeypatch)

    model = await _synced_model(db, synced_gateway_provider)
    assert model.pricing_input == 3.5
    assert model.pricing_output == 7.25
    assert model.cost_source == "catalog_pricing"


async def test_a_return_to_catalog_pricing_replaces_a_governed_free_zero(
    db, synced_gateway_provider, monkeypatch
) -> None:
    await _sync(db, synced_gateway_provider, FakeLiteLLMGateway(), alias_with_cost(GOVERNED_FREE_COST), monkeypatch)
    await _sync(db, synced_gateway_provider, FakeLiteLLMGateway(), gateway_config(), monkeypatch)

    model = await _synced_model(db, synced_gateway_provider)
    assert (model.pricing_input, model.pricing_output) == (CATALOG_INPUT_PRICE, CATALOG_OUTPUT_PRICE)
    assert model.cost_source == "catalog_pricing"


def test_a_provider_without_a_cost_contract_keeps_its_plain_pricing_block() -> None:
    """Non-gateway sync is untouched: it still only ever adds a price."""

    priced = resolve_model_pricing_update({"id": "m", "pricing": {"prompt": "0.000002", "completion": "0.000008"}})
    silent = resolve_model_pricing_update({"id": "m"})
    zero_like = resolve_model_pricing_update({"id": "m", "pricing": {"prompt": "0", "completion": None}})

    assert (priced.pricing_input, priced.pricing_output, priced.authoritative) == (2.0, 8.0, False)
    assert priced.cost_source is None
    assert (silent.pricing_input, silent.pricing_output, silent.authoritative) == (None, None, False)
    assert (zero_like.pricing_input, zero_like.pricing_output, zero_like.authoritative) == (None, None, False)


def test_a_malformed_cost_contract_fails_the_sync_instead_of_keeping_stale_prices() -> None:
    with pytest.raises(ValueError, match="model_catalog_cost_source_unknown"):
        resolve_model_pricing_update(
            {"id": "m", COST_CONTRACT_PAYLOAD_KEY: {"source": "free_because_i_said_so"}},
            driver=GOVERNED_COST_SOURCE_DRIVER,
        )
    with pytest.raises(ValueError, match="model_catalog_cost_pricing_invalid"):
        resolve_model_pricing_update(
            {"id": "m", COST_CONTRACT_PAYLOAD_KEY: {"source": "catalog_pricing"}},
            driver=GOVERNED_COST_SOURCE_DRIVER,
        )


@pytest.mark.parametrize(("input_rate", "output_rate", "expected_denial"), UNUSABLE_CATALOG_RATES)
def test_an_unusable_per_token_rate_is_never_admitted(
    input_rate: Any, output_rate: Any, expected_denial: str
) -> None:
    """Admission side: each required rate qualifies on its own or the alias is denied."""

    admission = resolve_alias_admission(ALIAS, alias_with_cost(_catalog_pricing_cost(input_rate, output_rate)))

    assert admission.admitted is False
    assert admission.denial_reason == expected_denial


@pytest.mark.parametrize(("input_rate", "output_rate", "expected_denial"), UNUSABLE_CATALOG_RATES)
def test_an_unusable_per_token_rate_never_reaches_a_model_row(
    input_rate: Any, output_rate: Any, expected_denial: str
) -> None:
    """Sync side qualifies the same rates, so a hand-written catalog cannot slip one past."""

    with pytest.raises(ValueError, match="model_catalog_cost_pricing_invalid"):
        resolve_model_pricing_update(
            {"id": ALIAS, COST_CONTRACT_PAYLOAD_KEY: _catalog_pricing_cost(input_rate, output_rate)},
            driver=GOVERNED_COST_SOURCE_DRIVER,
        )


def test_two_strictly_positive_finite_rates_are_what_a_governed_catalog_price_is() -> None:
    """The positive case, so the qualification above is not merely "everything fails"."""

    admission = resolve_alias_admission(ALIAS, alias_with_cost(_catalog_pricing_cost(0.15, 0.6)))
    update = resolve_model_pricing_update(
        {"id": ALIAS, COST_CONTRACT_PAYLOAD_KEY: _catalog_pricing_cost(0.15, 0.6)},
        driver=GOVERNED_COST_SOURCE_DRIVER,
    )

    assert admission.admitted is True
    assert (admission.entry.cost.input_per_million_usd, admission.entry.cost.output_per_million_usd) == (0.15, 0.6)
    assert (update.pricing_input, update.pricing_output, update.cost_source) == (0.15, 0.6, "catalog_pricing")
    assert update.authoritative is True


async def test_admin_cannot_hand_edit_the_price_of_a_governed_model(db, synced_gateway_provider) -> None:
    model = await _synced_model(db, synced_gateway_provider)

    with pytest.raises(HTTPException) as excinfo:
        await _admin_provider_models.update_model(
            db,
            provider_id=synced_gateway_provider.id,
            model_id=model.id,
            payload={"pricing_input": 99.0},
        )

    assert excinfo.value.status_code == 409
    refreshed = await _synced_model(db, synced_gateway_provider)
    assert refreshed.pricing_input == CATALOG_INPUT_PRICE
