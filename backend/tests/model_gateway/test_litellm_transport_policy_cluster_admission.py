"""Which cluster-internal plaintext endpoints are admitted and which hosts, schemes and modes are refused."""

from __future__ import annotations

from typing import Any

import httpx

from app.services.model_gateway.litellm import build_gateway_config
from app.services.model_gateway.litellm.client import LiteLLMGatewayHttpClient
from app.services.model_gateway.litellm.endpoint import (
    ENDPOINT_DENIAL_HOST_NOT_ALLOWLISTED,
    ENDPOINT_DENIAL_INSECURE_OFF_LOOPBACK,
    GatewayEndpoint,
    is_cluster_internal_service_host,
)
from app.services.model_gateway.litellm.errors import (
    GATEWAY_STATE_CONFIGURATION_INVALID,
    GATEWAY_STATE_ENDPOINT_DENIED,
)
from app.services.model_gateway.litellm.network_path import HOP_ROLE_DIRECT_EGRESS, build_network_path_contract
from app.services.model_gateway.litellm.readiness import gateway_configuration_reason
from app.services.model_gateway.litellm.transport_codes import (
    PROXY_MODE_DIRECT,
    TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT,
    TLS_DENIAL_PLAINTEXT_NOT_CLUSTER_SERVICE,
    TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL,
)
from app.services.model_gateway.litellm.transport_policy import resolve_transport_policy
from tests.model_gateway.conftest import VIRTUAL_KEY, gateway_provider, public_bundle_tls
from tests.model_gateway.litellm_transport_policy_support import (
    CLUSTER_HOST,
    CLUSTER_URL,
    cluster_denial,
    cluster_section,
)


def test_only_a_fully_qualified_cluster_service_name_is_cluster_internal() -> None:
    for admitted in (
        CLUSTER_HOST,
        "gw.ns.svc.cluster.local",
        "pod-0.headless.ns.svc.cluster.local",
    ):
        assert is_cluster_internal_service_host(admitted) is True, admitted

    for refused in (
        "litellm.gateway.svc",
        "litellm.gateway",
        "gateway.svc.cluster.local",
        "svc.cluster.local",
        ".svc.cluster.local",
        "litellm.gateway.svc.cluster.local.",
        "litellm.gateway.svc.cluster.local.evil.example",
        "litellm.gateway.svc.cluster.localhost",
        "litellm.gateway.svc.other.local",
        "litellm.gateway.pod.cluster.local",
        "litellm.example.com",
        "10.0.0.5",
        "127.0.0.1",
        "LITELLM.GATEWAY.SVC.CLUSTER.LOCAL",
        "lite_llm.gateway.svc.cluster.local",
        "*.gateway.svc.cluster.local",
        "-bad.gateway.svc.cluster.local",
        "",
        None,
    ):
        assert is_cluster_internal_service_host(refused) is False, refused


def test_the_cluster_internal_mode_admits_an_attested_http_cluster_service() -> None:
    config = build_gateway_config(
        endpoint_url=CLUSTER_URL,
        virtual_key=VIRTUAL_KEY,
        config_json={"litellm_gateway": cluster_section()},
    )

    tls = config.transport.tls
    assert tls.mode == TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL
    assert tls.plaintext is True
    assert tls.cluster_internal is True
    assert tls.ssl_context() is None
    assert config.endpoint.cluster_internal is True
    assert config.endpoint.loopback is False
    assert config.transport.proxy.mode == PROXY_MODE_DIRECT
    # No TLS leg exists, so there is nothing to verify; the environment still
    # gets no vote and there is no proxy.
    assert config.transport.httpx_client_kwargs() == {"verify": False, "proxy": None, "trust_env": False}

    evidence = config.evidence()
    assert evidence["tls_mode"] == "plaintext_cluster_internal"
    assert evidence["tls_node_encryption"] == "wireguard"
    assert evidence["tls_attestation_reference"] == "cluster-attestation-2026-11-06"
    assert evidence["tls_attested_on"] == "2026-11-06"
    assert evidence["tls_ca_bundle_certificate_count"] == 0
    assert evidence["tls_ca_bundle_sha256"] == ""
    assert evidence["endpoint_scheme"] == "http"
    assert evidence["endpoint_cluster_internal"] is True

    contract = build_network_path_contract(endpoint=config.endpoint, transport=config.transport, probe=config.probe)
    assert contract.egress_rules() == (f"{HOP_ROLE_DIRECT_EGRESS}:http:{CLUSTER_HOST}:4000",)
    assert contract.tls_mode == TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL

    provider = gateway_provider(endpoint_url=CLUSTER_URL, config_json={"litellm_gateway": cluster_section()})
    assert gateway_configuration_reason(provider) == ""


def test_the_client_runs_without_a_proxy_or_ambient_trust_for_a_cluster_service(monkeypatch) -> None:
    config = build_gateway_config(
        endpoint_url=CLUSTER_URL,
        virtual_key=VIRTUAL_KEY,
        config_json={"litellm_gateway": cluster_section()},
    )
    captured: dict[str, Any] = {}

    class RecordingAsyncClient:
        def __init__(self, **kwargs: Any):
            captured.update(kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", RecordingAsyncClient)
    LiteLLMGatewayHttpClient(config)

    assert captured["proxy"] is None
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False
    assert str(captured["base_url"]).startswith(f"http://{CLUSTER_HOST}:4000")


def test_a_cluster_internal_declaration_does_not_open_any_other_plaintext_host() -> None:
    cases = [
        ("http://10.0.0.5:4000", ["10.0.0.5"]),
        ("http://litellm.gateway.svc:4000", ["litellm.gateway.svc"]),
        ("http://litellm.gateway:4000", ["litellm.gateway"]),
        ("http://litellm.example.com", ["litellm.example.com"]),
        (
            "http://litellm.gateway.svc.cluster.local.evil.example",
            ["litellm.gateway.svc.cluster.local.evil.example"],
        ),
        ("http://gateway.svc.cluster.local:4000", ["gateway.svc.cluster.local"]),
    ]
    for url, allowlist in cases:
        state, denial = cluster_denial(url, cluster_section(host_allowlist=allowlist))
        assert (url, state, denial) == (url, GATEWAY_STATE_ENDPOINT_DENIED, ENDPOINT_DENIAL_INSECURE_OFF_LOOPBACK)


def test_a_cluster_service_must_still_be_on_the_host_allowlist() -> None:
    state, denial = cluster_denial(CLUSTER_URL, cluster_section(host_allowlist=["other.ns.svc.cluster.local"]))

    assert (state, denial) == (GATEWAY_STATE_ENDPOINT_DENIED, ENDPOINT_DENIAL_HOST_NOT_ALLOWLISTED)


def test_an_http_cluster_service_needs_the_cluster_internal_mode() -> None:
    for tls in ({"mode": "plaintext_loopback"}, public_bundle_tls(), None):
        section = cluster_section(tls=tls)
        if tls is None:
            section.pop("tls")
        state, denial = cluster_denial(CLUSTER_URL, section)
        assert (state, denial) == (GATEWAY_STATE_ENDPOINT_DENIED, ENDPOINT_DENIAL_INSECURE_OFF_LOOPBACK), tls


def test_the_cluster_internal_mode_against_an_https_endpoint_is_a_conflict() -> None:
    state, denial = cluster_denial(f"https://{CLUSTER_HOST}:4000", cluster_section())

    assert (state, denial) == (GATEWAY_STATE_CONFIGURATION_INVALID, TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT)


def test_the_cluster_internal_mode_is_refused_on_loopback() -> None:
    state, denial = cluster_denial("http://127.0.0.1:4000/v1", cluster_section(host_allowlist=["127.0.0.1"]))

    assert (state, denial) == (GATEWAY_STATE_CONFIGURATION_INVALID, TLS_DENIAL_PLAINTEXT_NOT_CLUSTER_SERVICE)


def test_the_transport_policy_rechecks_the_cluster_service_host_itself() -> None:
    for host in ("10.0.0.5", "litellm.gateway.svc", "gateway.internal.test"):
        resolution = resolve_transport_policy(
            endpoint=GatewayEndpoint(
                base_url=f"http://{host}",
                scheme="http",
                host=host,
                port=None,
                base_path="",
                loopback=False,
                cluster_internal=True,
            ),
            section=cluster_section(),
        )
        assert resolution.policy is None, host
        assert resolution.denial_reason == TLS_DENIAL_PLAINTEXT_NOT_CLUSTER_SERVICE, host
