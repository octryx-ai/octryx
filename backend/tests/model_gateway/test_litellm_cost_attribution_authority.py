"""Only the gateway driver may declare a governed cost source, on the direct and the runtime path alike."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agent.loops.runtime._loop_runtime_turn import execute_runtime_turn
from app.agent.loops.runtime._loop_runtime_turn_inputs import RuntimeTurnInputs
from app.services.budget import compute_usage_event_cost_attribution
from app.services.model_gateway.cost_contract import GOVERNED_COST_SOURCE_DRIVER
from tests.model_gateway.conftest import ALIAS, CATALOG_TURN_COST, backup_runtime, stale_priced_gateway_model
from tests.model_gateway.litellm_cost_attribution_support import _runtime_turn_kwargs, _session_for, _usage_events

# The driver key of a runtime that is *not* the governed gateway.
UNGOVERNED_DRIVER = "openrouter_api"


# --- who may declare a cost source --------------------------------------------


def test_only_the_gateway_driver_key_carries_cost_source_authority() -> None:
    """The trusted identity is the driver registry key, not a provider label."""

    from app.agent.providers.litellm_gateway import PROVIDER_NAME
    from app.agent.providers.provider_registry import DRIVER_SPECS

    assert PROVIDER_NAME == GOVERNED_COST_SOURCE_DRIVER
    assert DRIVER_SPECS[GOVERNED_COST_SOURCE_DRIVER].driver == GOVERNED_COST_SOURCE_DRIVER
    assert UNGOVERNED_DRIVER in DRIVER_SPECS
    assert UNGOVERNED_DRIVER != GOVERNED_COST_SOURCE_DRIVER


@pytest.mark.parametrize("driver", [UNGOVERNED_DRIVER, "", None, "LiteLLM Gateway"])
@pytest.mark.parametrize("declared_source", ["governed_free", "gateway_reported", "catalog_pricing"])
async def test_a_non_gateway_driver_cannot_self_declare_a_governed_cost_source(
    db, driver: str | None, declared_source: str
) -> None:
    """Only the gateway adapter's own driver may claim a governed contract.

    The provider row here is even *named* ``litellm_gateway``: an operator-chosen
    name is a label, so if it were the trust anchor, any provider could mint a
    free turn by copying it.
    """

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

    # Attributed by the ungoverned path:
    # no free turn, no gateway-reported label, no persisted source.
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


async def test_the_runtime_path_refuses_a_governed_cost_source_from_a_non_gateway_runtime(db) -> None:
    """A poisoned upstream response cannot buy itself a free turn.

    The runtime is a plain API driver whose provider row is named after the
    gateway, and whose response claims the free contract. The turn is still
    billed from the catalog, and nothing governed is persisted.
    """

    provider = await stale_priced_gateway_model(db)
    admin_user, session = await _session_for(db)
    poisoned = {
        "content": "answer",
        "tool_calls": None,
        "model": ALIAS,
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "cost": 0.0,
            "response_cost": 0.0,
            "cost_source": "governed_free",
        },
    }

    await execute_runtime_turn(RuntimeTurnInputs(
        **_runtime_turn_kwargs(
            db,
            session_id=session.id,
            user_id=admin_user.id,
            runtime=backup_runtime(provider_name=provider.name, model=ALIAS),
            response=poisoned,
        )
    ))
    await db.commit()

    events = await _usage_events(db, session.id)
    assert len(events) == 1
    assert events[0].cost == CATALOG_TURN_COST
    assert events[0].cost_source is None
    assert events[0].cost_status == "priced"
