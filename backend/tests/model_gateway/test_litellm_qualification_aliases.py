"""Every admitted alias qualifies on usage, cost, model group and capabilities, and each contract violation is refused."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.model_gateway.litellm.errors import (
    GATEWAY_STATE_CAPABILITY_NOT_PROVEN,
    GATEWAY_STATE_FALLBACK_VIOLATION,
)
from app.services.model_gateway.litellm.qualification import (
    FailClosedExpectation,
    qualify_fail_closed,
    run_alias_qualification,
)
from app.services.model_gateway.litellm.qualification_codes import (
    CHECK_CAPABILITY_PARITY,
    CHECK_CATALOG_PROBE,
    CHECK_CONTENT_LOGGING_POSTURE,
    CHECK_COST_CONTRACT,
    CHECK_MODEL_GROUP_IDENTITY,
    CHECK_NETWORK_PATH_CONTRACT,
    CHECK_USAGE_INTEGRAL,
    FAIL_CLOSED_CAPABILITY_NOT_PROVEN,
    FAIL_CLOSED_FREE_CONTRACT_REPORTED_COST,
    FAIL_CLOSED_GATEWAY_COST_NOT_POSITIVE,
    FAIL_CLOSED_MODEL_GROUP_MISMATCH,
    FAIL_CLOSED_USAGE_NOT_REPORTED,
    REASON_CONTEXT_LIMIT_ABOVE_PROBE_MAX_INPUT,
    REASON_DECLARED_CAPABILITY_NOT_PROVEN,
    REASON_DECLARED_CAPABILITY_REFUTED,
    REASON_RESPONSE_ACCEPTED,
    REQUIRED_CHECK_CODES,
)
from app.services.model_gateway.litellm.qualification_report import QualificationCheck
from tests.model_gateway.litellm_qualification_support import (
    FAIL_CLOSED_CASES,
    FREE_ALIAS,
    FREE_GROUP,
    PRICED_ALIAS,
    PRICED_GROUP,
    PROBE_MAX_INPUT_TOKENS,
    REPORTED_ALIAS,
    REPORTED_GROUP,
    ScriptedGateway,
    build_client,
    chat_response,
    qualification_section,
)

# --- Positive qualification --------------------------------------------------


async def test_every_admitted_alias_qualifies_on_usage_cost_identity_and_capabilities() -> None:
    gateway = ScriptedGateway()
    client = build_client(gateway)
    try:
        checks = await run_alias_qualification(client=client, config=client.config)
    finally:
        await client.aclose()

    by_code: dict[str, list[QualificationCheck]] = {}
    for check in checks:
        by_code.setdefault(check.code, []).append(check)

    assert all(check.passed for check in checks), [check.to_evidence() for check in checks if not check.passed]
    assert set(by_code) == set(REQUIRED_CHECK_CODES)
    for code in (CHECK_CAPABILITY_PARITY, CHECK_USAGE_INTEGRAL, CHECK_COST_CONTRACT, CHECK_MODEL_GROUP_IDENTITY):
        assert {check.alias for check in by_code[code]} == {PRICED_ALIAS, REPORTED_ALIAS, FREE_ALIAS}

    costs = {check.alias: check.detail for check in by_code[CHECK_COST_CONTRACT]}
    assert costs[REPORTED_ALIAS]["cost_is_positive"] is True
    assert costs[PRICED_ALIAS]["cost_is_positive"] is True
    assert costs[FREE_ALIAS]["cost_is_zero"] is True
    assert costs[FREE_ALIAS]["cost_is_positive"] is False

    usage = {check.alias: check.detail for check in by_code[CHECK_USAGE_INTEGRAL]}
    assert usage[PRICED_ALIAS]["prompt_tokens"] == 1200
    assert usage[PRICED_ALIAS]["completion_tokens"] == 340

    probe = by_code[CHECK_CATALOG_PROBE][0].detail
    assert probe["model_group_count"] == 3
    assert by_code[CHECK_NETWORK_PATH_CONTRACT][0].detail["hop_count"] == 1
    assert by_code[CHECK_CONTENT_LOGGING_POSTURE][0].detail["live_confirmed"] is False


async def test_a_refuted_or_unproven_capability_fails_parity_before_dispatch() -> None:
    catalog = {
        "data": [
            {"id": PRICED_GROUP, "model_info": {"supports_function_calling": False}},
            {"id": REPORTED_GROUP, "model_info": {}},
            {"id": FREE_GROUP, "model_info": {"supports_function_calling": True}},
        ]
    }
    gateway = ScriptedGateway(catalog=catalog)
    client = build_client(gateway)
    try:
        checks = await run_alias_qualification(client=client, config=client.config)
    finally:
        await client.aclose()

    parity = {check.alias: check for check in checks if check.code == CHECK_CAPABILITY_PARITY}
    assert parity[PRICED_ALIAS].detail["reason"] == REASON_DECLARED_CAPABILITY_REFUTED
    assert parity[REPORTED_ALIAS].detail["reason"] == REASON_DECLARED_CAPABILITY_NOT_PROVEN
    assert parity[FREE_ALIAS].passed is True
    # A parity failure stops that alias before a billable call is made.
    dispatched = [path for method, path in gateway.requests if method == "POST"]
    assert len(dispatched) == 1


async def test_a_context_limit_above_the_probe_maximum_fails_parity() -> None:
    section = qualification_section()
    section["aliases"][PRICED_ALIAS]["context_limit"] = PROBE_MAX_INPUT_TOKENS + 1
    gateway = ScriptedGateway()
    client = build_client(gateway, section)
    try:
        checks = await run_alias_qualification(client=client, config=client.config)
    finally:
        await client.aclose()

    parity = {check.alias: check for check in checks if check.code == CHECK_CAPABILITY_PARITY}
    assert parity[PRICED_ALIAS].detail["reason"] == REASON_CONTEXT_LIMIT_ABOVE_PROBE_MAX_INPUT
    assert parity[REPORTED_ALIAS].passed is True


async def test_a_probe_that_reports_no_model_group_stops_the_qualification() -> None:
    gateway = ScriptedGateway(catalog={"data": []})
    client = build_client(gateway)
    try:
        checks = await run_alias_qualification(client=client, config=client.config)
    finally:
        await client.aclose()

    assert [check.code for check in checks] == [
        CHECK_CONTENT_LOGGING_POSTURE,
        CHECK_NETWORK_PATH_CONTRACT,
        CHECK_CATALOG_PROBE,
    ]
    assert checks[-1].passed is False
    assert not [path for method, path in gateway.requests if method == "POST"]


@pytest.mark.parametrize(("code", "state", "denial", "overrides"), FAIL_CLOSED_CASES)
async def test_a_response_violating_the_contract_is_refused(
    code: str, state: str, denial: str, overrides: dict[str, Any]
) -> None:
    alias, group = {
        FAIL_CLOSED_MODEL_GROUP_MISMATCH: (PRICED_ALIAS, PRICED_GROUP),
        FAIL_CLOSED_USAGE_NOT_REPORTED: (PRICED_ALIAS, PRICED_GROUP),
        FAIL_CLOSED_GATEWAY_COST_NOT_POSITIVE: (REPORTED_ALIAS, REPORTED_GROUP),
        FAIL_CLOSED_FREE_CONTRACT_REPORTED_COST: (FREE_ALIAS, FREE_GROUP),
    }[code]
    gateway = ScriptedGateway(chat={group: chat_response(group, **overrides)})
    client = build_client(gateway)
    entry = next(item for item in client.config.aliases if item.alias == alias)
    try:
        check = await qualify_fail_closed(
            FailClosedExpectation(code, state, denial),
            lambda: client.chat_completion(entry=entry, messages=[{"role": "user", "content": "ping"}]),
        )
    finally:
        await client.aclose()

    assert check.passed, check.to_evidence()
    assert check.detail["gateway_state"] == state


async def test_zero_catalog_pricing_rate_is_refused_before_dispatch() -> None:
    """A zero per-token rate is not a partially free priced alias."""

    gateway = ScriptedGateway(
        chat={PRICED_GROUP: chat_response(PRICED_GROUP, usage={"prompt_tokens": 1, "completion_tokens": 0})}
    )
    section = qualification_section()
    section["aliases"][PRICED_ALIAS]["cost"] = {
        "source": "catalog_pricing",
        "input_per_million_usd": 0.0,
        "output_per_million_usd": 1e-12,
    }
    client = build_client(gateway, section)
    try:
        assert all(item.alias != PRICED_ALIAS for item in client.config.aliases)
        assert gateway.requests == []
    finally:
        await client.aclose()


async def test_an_unproven_capability_request_is_refused() -> None:
    gateway = ScriptedGateway(catalog={"data": [{"id": PRICED_GROUP, "model_info": {}}]})
    client = build_client(gateway)
    entry = next(item for item in client.config.aliases if item.alias == PRICED_ALIAS)
    try:
        check = await qualify_fail_closed(
            FailClosedExpectation(FAIL_CLOSED_CAPABILITY_NOT_PROVEN, GATEWAY_STATE_CAPABILITY_NOT_PROVEN),
            lambda: client.chat_completion(
                entry=entry,
                messages=[{"role": "user", "content": "ping"}],
                tools=[{"type": "function", "function": {"name": "noop", "parameters": {}}}],
            ),
        )
    finally:
        await client.aclose()

    assert check.passed, check.to_evidence()
    assert not [path for method, path in gateway.requests if method == "POST"]


async def test_an_accepted_violation_is_the_worst_outcome_and_fails() -> None:
    """If the client ever served a forbidden response, the check must fail."""

    gateway = ScriptedGateway()
    client = build_client(gateway)
    entry = next(item for item in client.config.aliases if item.alias == PRICED_ALIAS)
    try:
        accepted = await qualify_fail_closed(
            FailClosedExpectation(FAIL_CLOSED_MODEL_GROUP_MISMATCH, GATEWAY_STATE_FALLBACK_VIOLATION),
            lambda: client.chat_completion(entry=entry, messages=[{"role": "user", "content": "ping"}]),
        )
        wrong_state = await qualify_fail_closed(
            FailClosedExpectation(FAIL_CLOSED_USAGE_NOT_REPORTED, GATEWAY_STATE_FALLBACK_VIOLATION),
            lambda: client.chat_completion(entry=entry, messages=[{"role": "user", "content": "ping"}], tools=None),
        )
    finally:
        await client.aclose()

    assert accepted.passed is False
    assert accepted.detail["reason"] == REASON_RESPONSE_ACCEPTED
    assert wrong_state.passed is False
