"""Trust boundary of the governed transport."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Any

import pytest

from app.services.model_gateway.litellm.endpoint import validate_gateway_endpoint
from app.services.model_gateway.litellm.errors import (
    GATEWAY_STATE_CONFIGURATION_INVALID,
    LiteLLMGatewayError,
)
from app.services.model_gateway.litellm.proxy_trust import (
    PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED,
    PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE,
    PROXY_TLS_TRUST_NOT_APPLICABLE,
    resolve_proxy_tls_trust,
)
from app.services.model_gateway.litellm.readiness import gateway_configuration_reason
from app.services.model_gateway.litellm.transport_codes import TLS_MODE_PLAINTEXT_LOOPBACK
from app.services.model_gateway.litellm.transport_decisions import GovernedProxy, TlsTrustPolicy, TransportPolicy
from app.services.model_gateway.litellm.transport_policy import resolve_transport_policy
from tests.model_gateway.conftest import (
    BASE_URL,
    gateway_provider,
    gateway_section,
    public_bundle_tls,
    write_ca_bundle,
)

GENUINE_CA = "Genuine CA"
ROTATED_CA = "Rotated CA"
PROXY_HOST = "egress.nonprod.example.com"
HTTPS_PROXY_URL = f"https://{PROXY_HOST}:3128"
HTTP_PROXY_URL = f"http://{PROXY_HOST}:3128"


def resolve(endpoint_url: str, section: dict[str, Any]):
    validation = validate_gateway_endpoint(endpoint_url, allowed_hosts=section["host_allowlist"])
    assert validation.endpoint is not None
    return resolve_transport_policy(endpoint=validation.endpoint, section=section)


def governed_proxy_section(url: str, **overrides: Any) -> dict[str, Any]:
    return gateway_section(
        proxy={"mode": "governed_proxy", "url": url, "host_allowlist": [PROXY_HOST]},
        **overrides,
    )


def subjects_of(context: ssl.SSLContext) -> list[str]:
    return [entry["subject"][0][0][1] for entry in context.get_ca_certs()]


def write_same_size_bundle(path: Path, *, common_name: str, size: int) -> None:
    scratch = path.parent / f".{path.name}.scratch"
    write_ca_bundle(scratch, common_name=common_name)
    material = scratch.read_bytes()
    scratch.unlink()
    assert len(material) <= size, "padding cannot shrink a bundle"
    path.write_bytes(material + b"\n" * (size - len(material)))


def test_a_same_size_same_mtime_rotation_is_revalidated_not_served_from_cache(tmp_path) -> None:
    bundle = tmp_path / "ca.pem"
    write_ca_bundle(bundle, common_name=GENUINE_CA)
    original_size = bundle.stat().st_size
    write_same_size_bundle(bundle, common_name=GENUINE_CA, size=original_size + 64)
    tls = {"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)}

    first = resolve(BASE_URL, gateway_section(tls=tls)).policy
    assert first is not None
    assert subjects_of(first.tls.ssl_context()) == [GENUINE_CA]
    before = bundle.stat()

    # The rotation an operator really performs: same size, and ``cp -p`` style
    # metadata preservation, here reproduced exactly with ``utime``.
    write_same_size_bundle(bundle, common_name=ROTATED_CA, size=before.st_size)
    os.utime(bundle, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = bundle.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)

    second = resolve(BASE_URL, gateway_section(tls=tls)).policy

    assert second is not None
    assert second.tls.bundle_sha256 != first.tls.bundle_sha256
    assert subjects_of(second.tls.ssl_context()) == [ROTATED_CA]


def test_an_unchanged_bundle_is_still_served_from_the_validation_cache(tmp_path) -> None:
    bundle = tmp_path / "ca.pem"
    write_ca_bundle(bundle, common_name=GENUINE_CA)
    tls = {"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)}

    first = resolve(BASE_URL, gateway_section(tls=tls)).policy
    second = resolve(BASE_URL, gateway_section(tls=tls)).policy

    assert first is not None and second is not None
    assert first.tls.bundle_sha256 == second.tls.bundle_sha256
    # Same digest means the same cached context object, not a second parse.
    assert first.tls.ssl_context() is second.tls.ssl_context()


def test_an_https_proxy_without_a_validated_trust_store_is_refused() -> None:
    section = governed_proxy_section(
        HTTPS_PROXY_URL,
        host_allowlist=["127.0.0.1"],
        tls={"mode": TLS_MODE_PLAINTEXT_LOOPBACK},
    )

    resolution = resolve("http://127.0.0.1:4000/v1", section)

    assert resolution.policy is None
    assert resolution.denial_reason == PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED


def test_the_refusal_reaches_the_operator_readiness_surface() -> None:
    provider = gateway_provider(
        endpoint_url="http://127.0.0.1:4000/v1",
        config_json={
            "litellm_gateway": governed_proxy_section(
                HTTPS_PROXY_URL,
                host_allowlist=["127.0.0.1"],
                tls={"mode": TLS_MODE_PLAINTEXT_LOOPBACK},
            )
        },
    )

    assert gateway_configuration_reason(provider) == (
        f"litellm_gateway_{PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED}"
    )


def test_an_https_proxy_records_the_trust_store_its_leg_is_verified_against() -> None:
    resolution = resolve(BASE_URL, governed_proxy_section(HTTPS_PROXY_URL))

    policy = resolution.policy
    assert policy is not None
    assert policy.proxy.tls_leg is True
    assert policy.proxy.tls_trust_source == PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE
    assert policy.evidence()["proxy_tls_trust_source"] == PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE
    assert isinstance(policy.httpx_client_kwargs()["verify"], ssl.SSLContext)


def test_a_plaintext_proxy_hop_has_no_tls_leg_to_trust() -> None:
    resolution = resolve(BASE_URL, governed_proxy_section(HTTP_PROXY_URL))

    policy = resolution.policy
    assert policy is not None
    assert policy.proxy.tls_leg is False
    assert policy.proxy.tls_trust_source == PROXY_TLS_TRUST_NOT_APPLICABLE
    assert policy.evidence()["proxy_tls_trust_source"] == PROXY_TLS_TRUST_NOT_APPLICABLE


def test_no_admitted_combination_ever_verifies_a_proxy_leg_with_verify_false(tmp_path) -> None:
    bundle = write_ca_bundle(tmp_path / "ca.pem", common_name=GENUINE_CA)
    combinations: list[tuple[str, dict[str, Any], Any]] = [
        (BASE_URL, public_bundle_tls(), None),
        (BASE_URL, public_bundle_tls(), HTTPS_PROXY_URL),
        (BASE_URL, public_bundle_tls(), HTTP_PROXY_URL),
        (BASE_URL, {"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)}, HTTPS_PROXY_URL),
        ("http://127.0.0.1:4000/v1", {"mode": TLS_MODE_PLAINTEXT_LOOPBACK}, None),
    ]

    admitted = 0
    for endpoint_url, tls, proxy_url in combinations:
        hosts = ["127.0.0.1"] if "127.0.0.1" in endpoint_url else None
        section = (
            governed_proxy_section(proxy_url, tls=tls)
            if proxy_url
            else gateway_section(tls=tls, proxy={"mode": "direct"})
        )
        if hosts:
            section["host_allowlist"] = hosts
        policy = resolve(endpoint_url, section).policy
        assert policy is not None, (endpoint_url, tls, proxy_url)
        admitted += 1
        kwargs = policy.httpx_client_kwargs()
        if policy.proxy.tls_leg:
            assert isinstance(kwargs["verify"], ssl.SSLContext), (endpoint_url, proxy_url)
    assert admitted == len(combinations)


def test_a_hand_built_policy_cannot_tunnel_through_an_unverified_proxy() -> None:
    policy = TransportPolicy(
        tls=TlsTrustPolicy(TLS_MODE_PLAINTEXT_LOOPBACK, "", 0, ""),
        proxy=GovernedProxy("governed_proxy", "https", PROXY_HOST, 3128, tls_trust_source=""),
    )

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        policy.httpx_client_kwargs()

    assert excinfo.value.gateway_state == GATEWAY_STATE_CONFIGURATION_INVALID
    assert excinfo.value.denial_reason == PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED


def test_the_proxy_trust_decision_is_pinned_directly() -> None:
    assert resolve_proxy_tls_trust(proxy_scheme="http", gateway_trust_store_validated=False) == (
        PROXY_TLS_TRUST_NOT_APPLICABLE,
        "",
    )
    assert resolve_proxy_tls_trust(proxy_scheme="https", gateway_trust_store_validated=True) == (
        PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE,
        "",
    )
    assert resolve_proxy_tls_trust(proxy_scheme="HTTPS", gateway_trust_store_validated=False) == (
        "",
        PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED,
    )
