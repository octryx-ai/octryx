"""Governed pricing, cost and usage numbers must be finite.

Every positivity rule in the gateway package is a comparison, and IEEE-754
``NaN`` is false for all of them — ``nan <= 0.0``, ``nan < 0.0`` and
``nan != 0.0`` alike — so a ``NaN`` would satisfy "must be strictly positive"
and land in budget attribution as a cost no threshold can compare against.
Infinity satisfies the same checks, and a large enough JSON integer makes
``float()`` itself raise.

Both untrusted sources are covered here: operator configuration (the alias cost
contract) and the gateway response body, which ``json.loads`` parses with the
``NaN``/``Infinity`` literals accepted by default.
"""

from __future__ import annotations

import json
import math

import pytest

from app.services.model_gateway.cost_contract import parse_reported_cost
from app.services.model_gateway.litellm import LiteLLMGatewayError, resolve_alias_admission
from app.services.model_gateway.litellm.client import GatewayChatResult
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION
from app.services.model_gateway.litellm.numeric_contract import finite_number
from app.services.model_gateway.litellm.qualification_alias_checks import _usage_checks
from app.services.model_gateway.litellm.qualification_codes import CHECK_COST_CONTRACT, REASON_COST_NOT_FINITE
from app.services.model_gateway.litellm.usage_contract import (
    COST_DENIAL_CATALOG_NOT_POSITIVE,
    USAGE_DENIAL_TOKENS_NOT_REPORTED,
    resolve_reported_tokens,
)
from tests.model_gateway.conftest import (
    ALIAS,
    GATEWAY_REPORTED_COST,
    MESSAGES,
    FakeLiteLLMGateway,
    alias_with_cost,
    chat_body,
    gateway_section,
)

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

NAN = float("nan")
INFINITY = float("inf")
# A JSON integer has no width limit, so a body can carry one that is not a float.
UNREPRESENTABLE_INTEGER = 10**400

NON_FINITE_NUMBERS = (NAN, INFINITY, -INFINITY, UNREPRESENTABLE_INTEGER)


def priced_alias(*, input_price: object, output_price: object) -> dict:
    return alias_with_cost(
        {
            "source": "catalog_pricing",
            "input_per_million_usd": input_price,
            "output_per_million_usd": output_price,
        }
    )


def test_finite_number_admits_only_real_finite_values() -> None:
    assert finite_number(1.5) == 1.5
    assert finite_number(3) == 3.0
    for value in NON_FINITE_NUMBERS:
        assert finite_number(value) is None
    # A bool is not a price, and a string is handled by its own parser.
    assert finite_number(True) is None
    assert finite_number("1.5") is None


def test_a_non_finite_catalog_price_is_not_admitted() -> None:
    """A NaN price passes ``< 0.0`` and ``sum <= 0.0``, so it has to be caught here."""

    observed: list[tuple[str, str]] = []
    for value in NON_FINITE_NUMBERS:
        for label, config_json in (
            ("input", priced_alias(input_price=value, output_price=2.0)),
            ("output", priced_alias(input_price=1.0, output_price=value)),
        ):
            admission = resolve_alias_admission(ALIAS, config_json)
            assert admission.admitted is False
            observed.append((label, admission.denial_reason))

    assert {reason for _label, reason in observed} == {"alias_cost_pricing_invalid"}


def test_a_non_finite_reported_cost_is_not_a_reported_cost() -> None:
    for value in NON_FINITE_NUMBERS:
        assert parse_reported_cost(value) is None
    # The string form never reaches float() because of the charset guard, but the
    # contract is the same either way.
    for text in ("nan", "inf", "-inf", "Infinity"):
        assert parse_reported_cost(text) is None
    assert parse_reported_cost(0.5) == 0.5


def test_a_non_finite_token_count_is_a_contract_violation_not_an_exception() -> None:
    """``int(nan)`` raises ``ValueError`` and ``int(inf)`` raises ``OverflowError``.

    Either one escaping this module would leave the gateway error boundary as an
    unclassified exception instead of a fixed response-contract denial.
    """

    for value in NON_FINITE_NUMBERS:
        with pytest.raises(LiteLLMGatewayError) as excinfo:
            resolve_reported_tokens({"prompt_tokens": value, "completion_tokens": 5})
        assert excinfo.value.gateway_state == GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION
        assert excinfo.value.denial_reason == USAGE_DENIAL_TOKENS_NOT_REPORTED

        with pytest.raises(LiteLLMGatewayError):
            resolve_reported_tokens({"prompt_tokens": 10, "completion_tokens": value})


def served_body(usage: str) -> bytes:
    """A conforming chat body with a hand-written ``usage`` object.

    Written as text rather than through ``json=`` because httpx serializes with
    ``allow_nan=False``; the point of these cases is the bare ``NaN``/``Infinity``
    literal a gateway can actually put on the wire.
    """

    body = chat_body()
    body.pop("usage")
    rendered = json.dumps(body)
    return f'{rendered[:-1]}, "usage": {usage}}}'.encode()


async def test_a_served_body_carrying_json_nan_usage_is_refused(build_gateway_client) -> None:
    gateway = FakeLiteLLMGateway(
        chat_content=served_body('{"prompt_tokens": NaN, "completion_tokens": 5}')
    )
    client = build_gateway_client(gateway, config_json=alias_with_cost(dict(GATEWAY_REPORTED_COST)))

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS)

    assert excinfo.value.gateway_state == GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION
    assert excinfo.value.denial_reason == USAGE_DENIAL_TOKENS_NOT_REPORTED


async def test_a_served_body_carrying_a_non_finite_reported_cost_is_refused(build_gateway_client) -> None:
    gateway = FakeLiteLLMGateway(
        chat_content=served_body('{"prompt_tokens": 10, "completion_tokens": 5, "cost": Infinity}')
    )
    client = build_gateway_client(gateway, config_json=alias_with_cost(dict(GATEWAY_REPORTED_COST)))

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS)

    # An infinite cost is "not reported", never a strictly positive one.
    assert excinfo.value.denial_reason == "gateway_cost_not_reported"


async def test_a_catalog_cost_that_overflows_to_infinity_is_refused(build_gateway_client) -> None:
    """Admitted finite prices can still multiply into infinity, which passes ``<= 0``."""

    section = gateway_section()
    section["aliases"][ALIAS]["cost"] = {
        "source": "catalog_pricing",
        "input_per_million_usd": 1e300,
        "output_per_million_usd": 1e300,
    }
    gateway = FakeLiteLLMGateway(
        chat_payload=chat_body(usage={"prompt_tokens": int(1e300), "completion_tokens": int(1e300)})
    )
    client = build_gateway_client(gateway, config_json={"litellm_gateway": section})

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS)

    assert excinfo.value.denial_reason == COST_DENIAL_CATALOG_NOT_POSITIVE


def test_the_qualification_cost_check_refuses_a_non_finite_cost() -> None:
    """The second, independent guard.

    ``resolve_usage_payload`` already guarantees a finite cost, so this state is
    unreachable through the client. It is asserted directly because the
    qualification report is what an activation decision is read from: a ``NaN``
    reaching it would be reported as a *passed* cost contract, since it is neither
    positive nor zero.
    """

    entry = resolve_alias_admission(ALIAS, alias_with_cost(dict(GATEWAY_REPORTED_COST))).entry
    result = GatewayChatResult(
        content="answer",
        tool_calls=None,
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "cost": NAN,
            "cost_source": entry.cost.source,
        },
        model_group=entry.model_group,
        proven_capabilities=frozenset(),
        evidence={"model_group_verified": True},
    )

    cost_check = next(check for check in _usage_checks(entry, result) if check.code == CHECK_COST_CONTRACT)

    assert cost_check.passed is False
    assert cost_check.detail["reason"] == REASON_COST_NOT_FINITE
    # Both comparisons are false for NaN.
    assert (NAN > 0.0) is False
    assert (NAN == 0.0) is False
    assert math.isnan(NAN)
