"""Activation qualification for the governed LiteLLM gateway: positive and fail-closed evidence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ...content_security.model_call_outbound import bound_constant
from .alias_catalog import (
    CAPABILITY_REASONING,
    CAPABILITY_TOOLS,
)
from .client import LiteLLMGatewayHttpClient
from .config import LiteLLMGatewayConfig
from .errors import LiteLLMGatewayError
from .network_path import build_network_path_contract
from .qualification_alias_checks import _alias_dispatch_failure, _capability_parity_check, _usage_checks
from .qualification_codes import (
    CHECK_CATALOG_PROBE,
    CHECK_CONTENT_LOGGING_POSTURE,
    CHECK_NETWORK_PATH_CONTRACT,
    QUALIFICATION_MESSAGES,
    QUALIFICATION_REASONING_EFFORT,
    QUALIFICATION_TOOLS,
    REASON_CATALOG_REPORTS_NO_MODEL_GROUP,
    REASON_ERROR_CARRIES_CAUSE,
    REASON_NETWORK_PATH_PORT_UNRESOLVED,
    REASON_POSTURE_NOT_LIVE_VERIFIED,
    REASON_RESPONSE_ACCEPTED,
    REASON_UNEXPECTED_DENIAL_REASON,
    REASON_UNEXPECTED_GATEWAY_STATE,
)
from .qualification_report import QualificationCheck, _failed, _passed, transport_assurance


def _content_logging_check(config: LiteLLMGatewayConfig) -> QualificationCheck:
    posture = config.content_logging
    # The posture is already admitted (``build_gateway_config`` refuses anything
    # that could retain prompts or credentials), so this check records *how* it was
    # verified: a declaration is accountable, but it is not live evidence.
    return _passed(
        CHECK_CONTENT_LOGGING_POSTURE,
        verified_against=posture.verified_against,
        live_confirmed=posture.live_confirmed,
        # ``disabled`` or ``retained_by_internal_platform_gateway``, verbatim.
        key_metadata_retention=posture.key_metadata_retention,
        callback_count=len(set(posture.success_callbacks) | set(posture.failure_callbacks)),
        pending_reason="" if posture.live_confirmed else REASON_POSTURE_NOT_LIVE_VERIFIED,
    )


def _network_path_check(config: LiteLLMGatewayConfig) -> QualificationCheck:
    contract = build_network_path_contract(
        endpoint=config.endpoint,
        transport=config.transport,
        probe=config.probe,
    )
    if any(hop.port <= 0 for hop in contract.hops):
        return _failed(CHECK_NETWORK_PATH_CONTRACT, reason=REASON_NETWORK_PATH_PORT_UNRESOLVED)
    return _passed(
        CHECK_NETWORK_PATH_CONTRACT,
        direction=contract.direction,
        hop_count=len(contract.hops),
        tls_mode=contract.tls_mode,
        node_encryption=config.transport.tls.node_encryption,
        transport_assurance=transport_assurance(config.transport.tls),
        proxy_mode=contract.proxy_mode,
        follows_redirects=contract.follows_redirects,
        trusts_ambient_environment=contract.trusts_ambient_environment,
        allowed_method_count=len(contract.allowed_methods),
    )


async def run_alias_qualification(
    *,
    client: LiteLLMGatewayHttpClient,
    config: LiteLLMGatewayConfig,
) -> list[QualificationCheck]:
    """Probe the catalog, then qualify every admitted alias with one real call."""

    checks: list[QualificationCheck] = [_content_logging_check(config), _network_path_check(config)]
    try:
        evidence = await client.probe_evidence(force_refresh=True)
    except LiteLLMGatewayError as error:
        checks.append(
            _failed(
                CHECK_CATALOG_PROBE,
                gateway_state=error.gateway_state,
                denial_reason=error.denial_reason,
            )
        )
        return checks
    if not evidence.model_groups:
        checks.append(_failed(CHECK_CATALOG_PROBE, reason=REASON_CATALOG_REPORTS_NO_MODEL_GROUP))
        return checks
    checks.append(
        _passed(
            CHECK_CATALOG_PROBE,
            models_path=config.probe.models_path,
            response_shape=config.probe.response_shape,
            model_group_field=config.probe.model_group_field,
            model_group_count=len(evidence.model_groups),
        )
    )

    for entry in config.aliases:
        parity = _capability_parity_check(entry, evidence)
        checks.append(parity)
        if not parity.passed:
            # A capability the catalog does not back would make the dispatch below
            # a refusal about configuration rather than about the response contract.
            continue
        try:
            with bound_constant():  # the constant probe through the final-bytes check (``model_call_outbound``)
                result = await client.chat_completion(
                    entry=entry,
                    messages=[dict(message) for message in QUALIFICATION_MESSAGES],
                    tools=[dict(tool) for tool in QUALIFICATION_TOOLS]
                    if CAPABILITY_TOOLS in entry.requested_capabilities
                    else None,
                    reasoning_effort=QUALIFICATION_REASONING_EFFORT
                    if CAPABILITY_REASONING in entry.requested_capabilities
                    else None,
                )
        except LiteLLMGatewayError as error:
            checks.extend(_alias_dispatch_failure(entry, error))
            continue
        checks.extend(_usage_checks(entry, result))
    return checks


@dataclass(frozen=True, slots=True)
class FailClosedExpectation:
    """One response the gateway client must refuse, and how."""

    code: str
    expected_state: str
    expected_denial_reason: str = ""


async def qualify_fail_closed(
    expectation: FailClosedExpectation,
    attempt: Callable[[], Awaitable[Any]],
) -> QualificationCheck:
    """Assert that ``attempt`` is refused with the expected state and no leakage."""

    accepted = False
    error: LiteLLMGatewayError | None = None
    try:
        with bound_constant():  # the attempt sends the constant probe through the final-bytes check
            await attempt()
        accepted = True
    except LiteLLMGatewayError as raised:
        error = raised
    if accepted or error is None:
        # An accepted response is the worst outcome: the gateway served something
        # the contract forbids and the client billed it as success.
        return _failed(expectation.code, reason=REASON_RESPONSE_ACCEPTED)
    if error.gateway_state != expectation.expected_state:
        return _failed(
            expectation.code,
            reason=REASON_UNEXPECTED_GATEWAY_STATE,
            gateway_state=error.gateway_state,
            expected_state=expectation.expected_state,
        )
    if expectation.expected_denial_reason and error.denial_reason != expectation.expected_denial_reason:
        return _failed(
            expectation.code,
            reason=REASON_UNEXPECTED_DENIAL_REASON,
            denial_reason=error.denial_reason,
            expected_denial_reason=expectation.expected_denial_reason,
        )
    if error.__cause__ is not None or error.__context__ is not None:
        # A surviving chain would carry transport text into persisted evidence.
        return _failed(expectation.code, reason=REASON_ERROR_CARRIES_CAUSE)
    return _passed(
        expectation.code,
        gateway_state=error.gateway_state,
        denial_reason=error.denial_reason,
    )


__all__ = [
    "FailClosedExpectation",
    "qualify_fail_closed",
    "run_alias_qualification",
]
