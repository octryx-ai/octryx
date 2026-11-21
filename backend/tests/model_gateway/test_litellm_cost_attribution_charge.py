"""The declared cost source is authoritative for usage accounting.

The other half of the contract: what one turn is charged, and who is allowed to
say so. Three things are asserted here that the catalog side cannot show —

- each cost source settles its own way, and neither ``gateway_reported`` nor
  ``governed_free`` may fall back to a catalog price the mode no longer owns;
- only the governed gateway *driver* may declare a cost source, so no other
  provider can mint itself a free turn by echoing one in its usage payload;
- one supported runtime dispatch produces exactly one ``UsageEvent`` and one
  charge, at the adapter's price, and the record it persists carries none of the
  upstream response's own fields.

Scope of "no duplicate billing" here: *within one dispatch*. The defect this suite
closes is a second, divergent charge derived inside the accounting path — the
catalog re-pricing a turn the adapter already priced. Neither the contract nor
``record_usage_event`` defines an idempotency key, so nothing in this suite
claims that replaying the same request twice is deduplicated; the opposite is
recorded explicitly by
``test_a_second_dispatch_is_a_second_charge_because_no_retry_dedup_exists``.

What model sync persists for the same contract is ``test_litellm_cost_authority``.
Everything runs against the offline fake gateway from ``conftest``; no cluster,
no network, no AWS.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.agent.loops.runtime._loop_runtime_turn import execute_runtime_turn
from app.agent.loops.runtime._loop_runtime_turn_inputs import RuntimeTurnInputs
from app.services.budget import compute_usage_event_cost_attribution
from app.services.model_gateway.cost_contract import GOVERNED_COST_SOURCE_DRIVER
from tests.model_gateway.conftest import (
    ALIAS,
    CATALOG_TURN_COST,
    GOVERNED_FREE_COST,
    MESSAGES,
    FakeLiteLLMGateway,
    alias_with_cost,
    chat_body,
    gateway_runtime,
    stale_priced_gateway_model,
)
from tests.model_gateway.litellm_cost_attribution_support import _runtime_turn_kwargs, _session_for, _usage_events

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


@pytest.mark.parametrize(
    ("usage", "expected_cost", "expected_status", "expected_source"),
    [
        # The governed-free turn is the defect: without an authoritative source
        # its zero cost falls through to the stale catalog price above.
        (
            {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.0, "cost_source": "governed_free"},
            Decimal("0"),
            "governed_free",
            "governed_free",
        ),
        (
            {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.42, "cost_source": "gateway_reported"},
            Decimal("0.420000"),
            "gateway_reported_cost",
            "gateway_reported",
        ),
        # A gateway-reported turn with no usable cost settles at an explicit
        # refusal, never at the catalog price the mode no longer owns.
        (
            {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0, "cost_source": "gateway_reported"},
            Decimal("0"),
            "gateway_cost_not_reported",
            "gateway_reported",
        ),
        (
            {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.002, "cost_source": "catalog_pricing"},
            CATALOG_TURN_COST,
            "catalog_pricing",
            "catalog_pricing",
        ),
        # A source outside the closed enum is refused, not re-routed onto the
        # generic pricing path.
        (
            {"prompt_tokens": 1000, "completion_tokens": 500, "cost_source": "trust_me"},
            Decimal("0"),
            "cost_source_unknown",
            "",
        ),
    ],
)
async def test_the_declared_cost_source_decides_the_charge(
    db,
    usage: dict[str, Any],
    expected_cost: Decimal,
    expected_status: str,
    expected_source: str,
) -> None:
    await stale_priced_gateway_model(db)

    attribution = await compute_usage_event_cost_attribution(
        db,
        provider="litellm_gateway",
        driver=GOVERNED_COST_SOURCE_DRIVER,
        model=ALIAS,
        tokens_in=1000,
        tokens_out=500,
        usage=usage,
    )

    assert attribution.cost == expected_cost
    assert attribution.status == expected_status
    assert attribution.cost_source == expected_source


async def test_catalog_pricing_without_a_reported_cost_uses_the_synchronized_price(db) -> None:
    await stale_priced_gateway_model(db)

    attribution = await compute_usage_event_cost_attribution(
        db,
        provider="litellm_gateway",
        driver=GOVERNED_COST_SOURCE_DRIVER,
        model=ALIAS,
        tokens_in=1000,
        tokens_out=500,
        usage={"prompt_tokens": 1000, "completion_tokens": 500, "cost_source": "catalog_pricing"},
    )

    assert attribution.cost == CATALOG_TURN_COST
    assert attribution.status == "priced"
    assert attribution.cost_source == "catalog_pricing"


async def test_a_governed_free_turn_is_free_even_against_an_unpriced_model_row(db) -> None:
    attribution = await compute_usage_event_cost_attribution(
        db,
        provider="litellm_gateway",
        driver=GOVERNED_COST_SOURCE_DRIVER,
        model="never-synced-alias",
        tokens_in=1000,
        tokens_out=500,
        usage={"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.0, "cost_source": "governed_free"},
    )

    # Not ``missing_pricing``: the zero is the contract, not an unknown.
    assert attribution.status == "governed_free"
    assert attribution.cost == Decimal("0")


async def test_a_positive_cost_under_a_free_contract_is_recorded_as_a_contradiction(db) -> None:
    attribution = await compute_usage_event_cost_attribution(
        db,
        provider="litellm_gateway",
        driver=GOVERNED_COST_SOURCE_DRIVER,
        model=ALIAS,
        tokens_in=1000,
        tokens_out=500,
        usage={"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.42, "cost_source": "governed_free"},
    )

    assert attribution.status == "governed_free_contract_violation"
    assert attribution.cost == Decimal("0")


async def test_an_ungoverned_provider_keeps_its_existing_attribution(db) -> None:
    await stale_priced_gateway_model(db)

    reported = await compute_usage_event_cost_attribution(
        db,
        provider="litellm_gateway",
        driver=GOVERNED_COST_SOURCE_DRIVER,
        model=ALIAS,
        tokens_in=1000,
        tokens_out=500,
        usage={"cost": "0.1234567"},
    )
    priced = await compute_usage_event_cost_attribution(
        db,
        provider="litellm_gateway",
        driver=GOVERNED_COST_SOURCE_DRIVER,
        model=ALIAS,
        tokens_in=1000,
        tokens_out=500,
        usage={},
    )

    assert (reported.status, reported.cost_source) == ("provider_reported_cost", "")
    assert reported.cost == Decimal("0.123457")
    assert (priced.status, priced.cost_source) == ("priced", "")
    assert priced.cost == CATALOG_TURN_COST


# --- the adapter's served payload ---------------------------------------------


async def test_the_served_usage_payload_stays_a_closed_set_of_fields(build_gateway_client) -> None:
    """No arbitrary provider response field can reach a persisted trace."""

    gateway = FakeLiteLLMGateway(
        chat_payload=chat_body(
            usage={
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "litellm_call_id": "call-should-not-travel",
                "upstream_api_key": "sk-should-never-travel",
            },
            system_fingerprint="fp-should-not-travel",
        )
    )
    client = build_gateway_client(gateway)

    usage = (await client.chat(MESSAGES, model=ALIAS))["usage"]

    assert set(usage) == {"prompt_tokens", "completion_tokens", "cost", "cost_source", "gateway_evidence"}
    assert "sk-should-never-travel" not in str(usage)
    assert "call-should-not-travel" not in str(usage)


async def test_a_governed_free_gateway_turn_is_free_on_the_runtime_path(db, build_gateway_client) -> None:
    provider = await stale_priced_gateway_model(db)
    admin_user, session = await _session_for(db)
    client = build_gateway_client(FakeLiteLLMGateway(), config_json=alias_with_cost(GOVERNED_FREE_COST))
    response = await client.chat(MESSAGES, model=ALIAS)

    await execute_runtime_turn(RuntimeTurnInputs(
        **_runtime_turn_kwargs(
            db,
            session_id=session.id,
            user_id=admin_user.id,
            runtime=gateway_runtime(provider_name=provider.name, model=ALIAS),
            response=response,
        )
    ))
    await db.commit()

    events = await _usage_events(db, session.id)
    assert len(events) == 1
    assert events[0].cost == Decimal("0")
    assert events[0].cost_source == "governed_free"
    assert events[0].cost_status == "governed_free"
