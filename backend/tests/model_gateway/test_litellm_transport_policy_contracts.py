"""Malformed TLS and proxy contracts, loopback-only plaintext trust and the governed proxy hop."""

from __future__ import annotations

from typing import Any

from app.services.model_gateway.litellm.endpoint import GatewayEndpoint
from app.services.model_gateway.litellm.transport_codes import (
    MAX_CA_BUNDLE_BYTES,
    PROXY_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED,
    PROXY_DENIAL_HOST_NOT_ALLOWLISTED,
    PROXY_DENIAL_MODE_UNKNOWN,
    PROXY_DENIAL_PLAINTEXT_REQUIRES_TLS_ENDPOINT,
    PROXY_DENIAL_QUERY_PRESENT,
    PROXY_DENIAL_SCHEME_NOT_SUPPORTED,
    PROXY_DENIAL_UNEXPECTED_PATH,
    PROXY_DENIAL_URL_NOT_CONFIGURED,
    PROXY_DENIAL_USERINFO_PRESENT,
    PROXY_MODE_DIRECT,
    PROXY_MODE_GOVERNED,
    TLS_DENIAL_BUNDLE_NO_CERTIFICATE,
    TLS_DENIAL_BUNDLE_NOT_A_FILE,
    TLS_DENIAL_BUNDLE_PATH_MISSING,
    TLS_DENIAL_BUNDLE_PATH_NOT_ABSOLUTE,
    TLS_DENIAL_BUNDLE_TOO_LARGE,
    TLS_DENIAL_CONTRACT_MISSING,
    TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT,
    TLS_DENIAL_MODE_UNKNOWN,
    TLS_DENIAL_PLAINTEXT_OFF_LOOPBACK,
)
from app.services.model_gateway.litellm.transport_policy import resolve_transport_policy
from tests.model_gateway.conftest import BASE_URL, gateway_section, public_bundle_tls
from tests.model_gateway.litellm_transport_policy_support import PROXY_HOST, PROXY_URL, resolve


def test_malformed_tls_contracts_are_refused_with_fixed_codes(tmp_path) -> None:
    empty = tmp_path / "empty.pem"
    empty.write_text("not a certificate\n")
    oversized = tmp_path / "large.pem"
    oversized.write_bytes(b"-----BEGIN CERTIFICATE-----\n" + b"a" * MAX_CA_BUNDLE_BYTES)

    cases: list[tuple[Any, str]] = [
        (None, TLS_DENIAL_CONTRACT_MISSING),
        ({}, TLS_DENIAL_MODE_UNKNOWN),
        ({"mode": "trust_everything"}, TLS_DENIAL_MODE_UNKNOWN),
        ({"mode": "private_ca_bundle"}, TLS_DENIAL_BUNDLE_PATH_MISSING),
        ({"mode": "private_ca_bundle", "ca_bundle_path": "relative/ca.pem"}, TLS_DENIAL_BUNDLE_PATH_NOT_ABSOLUTE),
        ({"mode": "private_ca_bundle", "ca_bundle_path": str(tmp_path)}, TLS_DENIAL_BUNDLE_NOT_A_FILE),
        ({"mode": "private_ca_bundle", "ca_bundle_path": str(tmp_path / "absent.pem")}, TLS_DENIAL_BUNDLE_NOT_A_FILE),
        ({"mode": "private_ca_bundle", "ca_bundle_path": str(empty)}, TLS_DENIAL_BUNDLE_NO_CERTIFICATE),
        ({"mode": "private_ca_bundle", "ca_bundle_path": str(oversized)}, TLS_DENIAL_BUNDLE_TOO_LARGE),
        ({"mode": "plaintext_loopback"}, TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT),
    ]

    observed = []
    for tls, _expected in cases:
        section = gateway_section()
        if tls is None:
            section.pop("tls")
        else:
            section["tls"] = tls
        resolution = resolve(BASE_URL, section)
        assert resolution.policy is None
        observed.append((tls, resolution.denial_reason))

    assert observed == cases


def test_plaintext_trust_is_admitted_on_loopback_only() -> None:
    section = gateway_section(host_allowlist=["127.0.0.1"], tls={"mode": "plaintext_loopback"})
    loopback = resolve("http://127.0.0.1:4000/v1", section)

    assert loopback.policy is not None
    assert loopback.policy.tls.plaintext is True
    assert loopback.policy.httpx_client_kwargs()["verify"] is False

    # The endpoint validator already refuses plain http off loopback, so this
    # second line of defence is exercised against a directly built endpoint: the
    # transport policy must not depend on another module's rule.
    off_loopback = resolve_transport_policy(
        endpoint=GatewayEndpoint(
            base_url="http://gateway.internal.test/v1",
            scheme="http",
            host="gateway.internal.test",
            port=None,
            base_path="/v1",
            loopback=False,
        ),
        section=gateway_section(tls={"mode": "plaintext_loopback"}),
    )

    assert off_loopback.policy is None
    assert off_loopback.denial_reason == TLS_DENIAL_PLAINTEXT_OFF_LOOPBACK


def test_a_tls_bundle_against_a_plaintext_endpoint_is_a_conflict() -> None:
    section = gateway_section(host_allowlist=["127.0.0.1"], tls=public_bundle_tls())

    resolution = resolve("http://127.0.0.1:4000/v1", section)

    assert resolution.policy is None
    assert resolution.denial_reason == TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT


def test_an_absent_proxy_section_is_the_explicit_direct_path() -> None:
    section = gateway_section()
    section.pop("proxy")

    resolution = resolve(BASE_URL, section)

    assert resolution.policy is not None
    assert resolution.policy.proxy.mode == PROXY_MODE_DIRECT
    assert resolution.policy.httpx_client_kwargs()["proxy"] is None
    assert resolution.policy.httpx_client_kwargs()["trust_env"] is False


def test_a_governed_proxy_is_the_only_configured_egress_hop() -> None:
    section = gateway_section(proxy={"mode": "governed_proxy", "url": PROXY_URL, "host_allowlist": [PROXY_HOST]})

    resolution = resolve(BASE_URL, section)

    proxy = resolution.policy.proxy
    assert proxy.mode == PROXY_MODE_GOVERNED
    assert (proxy.scheme, proxy.host, proxy.port) == ("https", PROXY_HOST, 3128)
    assert resolution.policy.httpx_client_kwargs()["proxy"] == PROXY_URL


def test_malformed_proxy_contracts_are_refused_with_fixed_codes() -> None:
    cases: list[tuple[Any, str]] = [
        ({}, PROXY_DENIAL_MODE_UNKNOWN),
        ({"mode": "transparent"}, PROXY_DENIAL_MODE_UNKNOWN),
        ({"mode": "governed_proxy", "host_allowlist": [PROXY_HOST]}, PROXY_DENIAL_URL_NOT_CONFIGURED),
        ({"mode": "governed_proxy", "url": PROXY_URL}, PROXY_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED),
        (
            {"mode": "governed_proxy", "url": f"socks5://{PROXY_HOST}:1080", "host_allowlist": [PROXY_HOST]},
            PROXY_DENIAL_SCHEME_NOT_SUPPORTED,
        ),
        (
            {
                "mode": "governed_proxy",
                "url": f"https://user:secret@{PROXY_HOST}:3128",
                "host_allowlist": [PROXY_HOST],
            },
            PROXY_DENIAL_USERINFO_PRESENT,
        ),
        (
            {"mode": "governed_proxy", "url": f"{PROXY_URL}?tenant=alpha", "host_allowlist": [PROXY_HOST]},
            PROXY_DENIAL_QUERY_PRESENT,
        ),
        (
            {"mode": "governed_proxy", "url": f"{PROXY_URL}/forward", "host_allowlist": [PROXY_HOST]},
            PROXY_DENIAL_UNEXPECTED_PATH,
        ),
        (
            {"mode": "governed_proxy", "url": "https://other.proxy.test:3128", "host_allowlist": [PROXY_HOST]},
            PROXY_DENIAL_HOST_NOT_ALLOWLISTED,
        ),
    ]

    observed = []
    for proxy, _expected in cases:
        resolution = resolve(BASE_URL, gateway_section(proxy=proxy))
        assert resolution.policy is None
        observed.append((proxy, resolution.denial_reason))

    assert observed == cases


def test_a_plaintext_proxy_hop_needs_a_tls_gateway_leg() -> None:
    section = gateway_section(
        host_allowlist=["127.0.0.1"],
        tls={"mode": "plaintext_loopback"},
        proxy={"mode": "governed_proxy", "url": f"http://{PROXY_HOST}:3128", "host_allowlist": [PROXY_HOST]},
    )

    resolution = resolve("http://127.0.0.1:4000/v1", section)

    assert resolution.policy is None
    assert resolution.denial_reason == PROXY_DENIAL_PLAINTEXT_REQUIRES_TLS_ENDPOINT
