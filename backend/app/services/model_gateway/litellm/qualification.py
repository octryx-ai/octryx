"""Activation qualification for the governed LiteLLM gateway (Issue).

Before ``litellm_gateway`` may be enabled in a shared environment, the pinned
contract from has to be *proven* against the endpoint it will actually talk
to. This module owns what "proven" means, so the proof is identical whether it
runs against the deterministic local fixture in
``deployment/local/litellm-gateway/`` or, later, against the cluster gateway.

Two halves, both fail-closed:

``run_alias_qualification``
    Positive evidence: the catalog probe answers the pinned shape, each admitted
    alias' declared ``supports_*`` capabilities are backed by ``model_info``, a
    served response reports integral prompt/completion usage, settles its declared
    cost contract (``gateway_reported`` strictly positive, ``governed_free`` zero,
    ``catalog_pricing`` positive), and names the governed model group.

``qualify_fail_closed``
    Negative evidence: a response that violates one of those rules must be
    *refused* with the expected gateway state and a fixed message. A check that
    was never run is missing, and a missing required check keeps the gate closed.

``evidence_origin`` separates a local contract run from a live cluster run, and
``live_evidence_state`` stays ``pending_external_gate`` unless the run really was
against the external gateway *and* the content-logging posture was verified
against the running deployment.

Both of those are declarations — ``evidence_origin`` is a caller argument and
``verified_against`` is a string in the provider config — so on their own two
edits would let a local fixture close the activation gate. The state therefore
also requires facts the run cannot assert about itself: the validated endpoint
must not be loopback and the validated transport must not be plaintext. A local
fixture answers on ``127.0.0.1``, so it is *structurally* unable to present
itself as live proof, and the report records which of these conditions held the
gate open.

``plaintext_cluster_internal`` is the one plaintext transport that does not hold
the gate open: it is only admitted for a fully qualified cluster Service name with
the operator's node-encryption attestation, and it is the shape of a shared
in-cluster gateway rather than of a fixture. It is still not verified TLS, so the
report carries ``transport_assurance`` — ``verified_tls_chain`` for a CA bundle
mode, ``operator_attested_node_encryption`` for the cluster-internal mode — and
the network-path check records ``tls_mode`` and ``node_encryption``. A reviewer
reads the transport claim from those fields; ``gate_satisfied`` never upgrades it.

What ``LIVE_EVIDENCE_CONFIRMED`` is **not**: cryptographic proof that the peer
was the governed cluster gateway. The endpoint is checked by *name* against the
configured host allowlist, over a TLS chain the operator also configured, so what
the state records is "this run left this machine and reached the endpoint the
configuration names". Binding it to the deployment's identity — a pinned
certificate, an issued workload credential — is out of this module's scope.
``gate_satisfied`` is therefore **operator-reviewed evidence**: the report is
the artifact an operator reads against the environment they know (endpoint, CA
chain, virtual-key scope, model groups, content-logging configuration) before
activating the driver. It is not an automated attestation, and no caller should
present it as one.

Nothing here reads a prompt, a response body, a header, or a transport string into
its output: the probe prompt is a constant owned by this module, and every detail
value is filtered to numbers, booleans, and closed lowercase codes.
"""

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
