"""Operator attestation, the direct-only rule and dispatch for cluster-internal gateways."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.model_gateway.litellm import LiteLLMGatewayError, build_gateway_config
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_CONFIGURATION_INVALID
from app.services.model_gateway.litellm.transport_codes import (
    PROXY_DENIAL_CLUSTER_INTERNAL_REQUIRES_DIRECT,
    PROXY_MODE_DIRECT,
    PROXY_MODE_GOVERNED,
    TLS_DENIAL_ATTESTATION_REFERENCE_MISSING,
    TLS_DENIAL_ATTESTED_ON_INVALID,
    TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED,
    TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL,
)
from app.services.model_gateway.litellm.transport_decisions import GovernedProxy, TlsTrustPolicy, TransportPolicy
from tests.model_gateway.conftest import VIRTUAL_KEY
from tests.model_gateway.litellm_transport_policy_support import (
    CLUSTER_HOST,
    CLUSTER_TLS,
    CLUSTER_URL,
    PROXY_HOST,
    PROXY_URL,
    cluster_denial,
    cluster_section,
)

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


def test_the_cluster_internal_mode_needs_the_operator_attestation() -> None:
    def without(key: str) -> dict[str, Any]:
        return {name: value for name, value in CLUSTER_TLS.items() if name != key}

    cases: list[tuple[dict[str, Any], str]] = [
        (without("node_encryption"), TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED),
        ({**CLUSTER_TLS, "node_encryption": ""}, TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED),
        ({**CLUSTER_TLS, "node_encryption": "none"}, TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED),
        ({**CLUSTER_TLS, "node_encryption": "ipsec"}, TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED),
        ({**CLUSTER_TLS, "node_encryption": "mtls_probably"}, TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED),
        ({**CLUSTER_TLS, "node_encryption": ["wireguard"]}, TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED),
        ({**CLUSTER_TLS, "node_encryption": True}, TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED),
        (without("attestation_reference"), TLS_DENIAL_ATTESTATION_REFERENCE_MISSING),
        ({**CLUSTER_TLS, "attestation_reference": "see the wiki page"}, TLS_DENIAL_ATTESTATION_REFERENCE_MISSING),
        (without("attested_on"), TLS_DENIAL_ATTESTED_ON_INVALID),
        ({**CLUSTER_TLS, "attested_on": "last week"}, TLS_DENIAL_ATTESTED_ON_INVALID),
        ({**CLUSTER_TLS, "attested_on": "2026-02-30"}, TLS_DENIAL_ATTESTED_ON_INVALID),
        ({**CLUSTER_TLS, "attested_on": "20261106"}, TLS_DENIAL_ATTESTED_ON_INVALID),
    ]

    observed = []
    for tls, _expected in cases:
        state, denial = cluster_denial(CLUSTER_URL, cluster_section(tls=tls))
        assert state == GATEWAY_STATE_CONFIGURATION_INVALID
        observed.append((tls, denial))

    assert observed == cases


def test_the_cluster_internal_mode_is_direct_only() -> None:
    """The virtual key travels in clear, so no egress hop may carry it further."""

    for proxy in (
        {"mode": "governed_proxy", "url": PROXY_URL, "host_allowlist": [PROXY_HOST]},
        {"mode": "governed_proxy", "url": f"http://{PROXY_HOST}:3128", "host_allowlist": [PROXY_HOST]},
        {"mode": "governed_proxy"},
    ):
        state, denial = cluster_denial(CLUSTER_URL, cluster_section(proxy=proxy))
        assert (state, denial) == (
            GATEWAY_STATE_CONFIGURATION_INVALID,
            PROXY_DENIAL_CLUSTER_INTERNAL_REQUIRES_DIRECT,
        ), proxy

    # An absent proxy section is the explicit direct path, as for every mode.
    section = cluster_section()
    section.pop("proxy")
    config = build_gateway_config(
        endpoint_url=CLUSTER_URL, virtual_key=VIRTUAL_KEY, config_json={"litellm_gateway": section}
    )
    assert config.transport.proxy.mode == PROXY_MODE_DIRECT


def test_a_hand_built_cluster_internal_policy_with_a_proxy_builds_no_client() -> None:
    """Structural backstop behind ``_resolve_proxy`` in ``httpx_client_kwargs``."""

    policy = TransportPolicy(
        tls=TlsTrustPolicy(
            TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL,
            "",
            0,
            "",
            node_encryption="wireguard",
            attestation_reference="cluster-attestation-2026-11-06",
            attested_on="2026-11-06",
        ),
        proxy=GovernedProxy(PROXY_MODE_GOVERNED, "http", PROXY_HOST, 3128, tls_trust_source="not_applicable"),
    )

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        policy.httpx_client_kwargs()

    assert excinfo.value.denial_reason == PROXY_DENIAL_CLUSTER_INTERNAL_REQUIRES_DIRECT


async def test_a_refused_cluster_internal_config_dispatches_nothing(gateway, build_gateway_client) -> None:
    for tls in (
        {**CLUSTER_TLS, "node_encryption": "none"},
        {key: value for key, value in CLUSTER_TLS.items() if key != "attestation_reference"},
    ):
        with pytest.raises(LiteLLMGatewayError):
            build_gateway_client(
                gateway,
                endpoint_url=CLUSTER_URL,
                config_json={"litellm_gateway": cluster_section(tls=tls)},
            )

    assert gateway.requests == []


async def test_an_admitted_cluster_internal_gateway_dispatches_and_records_its_transport(
    gateway, build_gateway_client
) -> None:
    client = build_gateway_client(
        gateway,
        endpoint_url=f"{CLUSTER_URL}/v1",
        config_json={"litellm_gateway": cluster_section()},
    )

    response = await client.chat([{"role": "user", "content": "hello"}], model="octryx-general")

    assert len(gateway.chat_requests) == 1
    request = gateway.chat_requests[0]
    assert (request.url.scheme, request.url.host, request.url.port) == ("http", CLUSTER_HOST, 4000)
    evidence = response["usage"]["gateway_evidence"]
    assert evidence["tls_mode"] == "plaintext_cluster_internal"
    assert evidence["tls_node_encryption"] == "wireguard"
    assert evidence["proxy_mode"] == "direct"
