"""A response is accepted only with an established cost: a positive reported or catalog-priced cost with usable usage, never a silent zero except under the governed free contract."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.model_gateway.litellm import LiteLLMGatewayError
from app.services.model_gateway.litellm.alias_catalog import AliasCostContract, AliasEntry
from app.services.model_gateway.litellm.errors import (
    GATEWAY_STATE_CONFIGURATION_INVALID,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
)
from app.services.model_gateway.litellm.usage_contract import resolve_usage_payload
from tests.model_gateway.conftest import (
    ALIAS,
    GATEWAY_REPORTED_COST,
    GOVERNED_FREE_COST,
    MESSAGES,
    MODEL_GROUP,
    FakeLiteLLMGateway,
    alias_with_cost,
    chat_body,
    gateway_section,
)

#: These tests call provider drivers directly: they run as the platform (``tests/support/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


async def test_catalog_priced_alias_reports_a_non_zero_cost(gateway, build_gateway_client) -> None:
    client = build_gateway_client(gateway)

    response = await client.chat(MESSAGES, model=ALIAS)

    # 1000 prompt tokens at 1.0/1M + 500 completion tokens at 2.0/1M.
    assert response["usage"]["cost"] == pytest.approx(0.002)
    assert response["usage"]["cost_source"] == "catalog_pricing"
    assert response["usage"]["prompt_tokens"] == 1000
    assert response["usage"]["completion_tokens"] == 500


@pytest.mark.parametrize(
    ("reported_cost", "expected_reason"),
    [
        # A zero-like cost is the dangerous shape: budget attribution reads 0,
        # "0" and 0.0 as "not reported" and settles the turn at zero.
        (0, "gateway_cost_not_positive"),
        ("0", "gateway_cost_not_positive"),
        (-1.5, "gateway_cost_not_reported"),
        ("free", "gateway_cost_not_reported"),
        # ``bool`` is an ``int`` in Python: True must not pass as a price.
        (True, "gateway_cost_not_reported"),
        (None, "gateway_cost_not_reported"),
    ],
)
async def test_gateway_reported_cost_must_be_positive_and_numeric(
    build_gateway_client,
    reported_cost: Any,
    expected_reason: str,
) -> None:
    usage: dict[str, Any] = {"prompt_tokens": 10, "completion_tokens": 5}
    if reported_cost is not None:
        usage["cost"] = reported_cost
    gateway = FakeLiteLLMGateway(chat_payload=chat_body(usage=usage))
    client = build_gateway_client(gateway, config_json=alias_with_cost(GATEWAY_REPORTED_COST))

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS)

    assert excinfo.value.gateway_state == GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION
    assert excinfo.value.denial_reason == expected_reason


async def test_positive_reported_cost_is_accepted_from_either_field(build_gateway_client) -> None:
    in_usage = FakeLiteLLMGateway(
        chat_payload=chat_body(usage={"prompt_tokens": 10, "completion_tokens": 5, "cost": "0.0125"})
    )
    top_level = FakeLiteLLMGateway(
        chat_payload=chat_body(usage={"prompt_tokens": 10, "completion_tokens": 5}, response_cost=0.5)
    )
    config = alias_with_cost(GATEWAY_REPORTED_COST)

    from_usage = await build_gateway_client(in_usage, config_json=config).chat(MESSAGES, model=ALIAS)
    from_top_level = await build_gateway_client(top_level, config_json=config).chat(MESSAGES, model=ALIAS)

    assert from_usage["usage"]["cost"] == pytest.approx(0.0125)
    assert from_usage["usage"]["cost_source"] == "gateway_reported"
    assert from_top_level["usage"]["cost"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("usage_payload", "expected_reason"),
    [
        (None, "usage_not_reported"),
        ({"completion_tokens": 5}, "usage_tokens_not_reported"),
        ({"prompt_tokens": "1000", "completion_tokens": 5}, "usage_tokens_not_reported"),
        ({"prompt_tokens": True, "completion_tokens": 5}, "usage_tokens_not_reported"),
        ({"prompt_tokens": -10, "completion_tokens": 5}, "usage_tokens_not_reported"),
        ({"prompt_tokens": 0, "completion_tokens": 5}, "usage_prompt_tokens_not_positive"),
    ],
)
async def test_catalog_pricing_requires_usable_reported_usage(
    build_gateway_client,
    usage_payload: dict[str, Any] | None,
    expected_reason: str,
) -> None:
    payload = chat_body()
    if usage_payload is None:
        payload.pop("usage")
    else:
        payload["usage"] = usage_payload
    client = build_gateway_client(FakeLiteLLMGateway(chat_payload=payload))

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS)

    assert excinfo.value.gateway_state == GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION
    assert excinfo.value.denial_reason == expected_reason


async def test_a_billable_alias_can_never_settle_at_zero_cost(gateway, build_gateway_client) -> None:
    for rates in (
        {"input_per_million_usd": 0.0, "output_per_million_usd": 2.0},
        {"input_per_million_usd": 1.0, "output_per_million_usd": 0.0},
    ):
        section = gateway_section()
        section["aliases"][ALIAS]["cost"] = {"source": "catalog_pricing", **rates}

        with pytest.raises(LiteLLMGatewayError) as excinfo:
            build_gateway_client(gateway, config_json={"litellm_gateway": section})

        assert excinfo.value.gateway_state == GATEWAY_STATE_CONFIGURATION_INVALID
        assert excinfo.value.denial_reason == "alias_catalog_has_no_admitted_alias"

    assert gateway.requests == []


def test_the_response_contract_still_refuses_a_non_positive_computed_cost() -> None:
    entry = AliasEntry(
        alias=ALIAS,
        model_group=MODEL_GROUP,
        context_limit=128000,
        data_policy_class="internal",
        requested_capabilities=frozenset(),
        cost=AliasCostContract("catalog_pricing", 0.0, 0.0, ""),
    )

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        resolve_usage_payload(entry, {}, {"prompt_tokens": 10, "completion_tokens": 5})

    assert excinfo.value.gateway_state == GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION
    assert excinfo.value.denial_reason == "catalog_cost_not_positive"


async def test_governed_free_contract_is_the_only_admitted_zero_cost(build_gateway_client) -> None:
    gateway = FakeLiteLLMGateway(chat_payload=chat_body(usage={"prompt_tokens": 10, "completion_tokens": 5}))
    client = build_gateway_client(gateway, config_json=alias_with_cost(GOVERNED_FREE_COST))

    response = await client.chat(MESSAGES, model=ALIAS)

    assert response["usage"]["cost"] == 0.0
    assert response["usage"]["cost_source"] == "governed_free"
    evidence = response["usage"]["gateway_evidence"]
    assert evidence["cost_contract_reference"] == GOVERNED_FREE_COST["contract_reference"]


async def test_governed_free_alias_refuses_a_positive_reported_cost(build_gateway_client) -> None:
    gateway = FakeLiteLLMGateway(
        chat_payload=chat_body(usage={"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.42})
    )
    client = build_gateway_client(gateway, config_json=alias_with_cost(GOVERNED_FREE_COST))

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS)

    assert excinfo.value.denial_reason == "free_contract_reported_cost"
