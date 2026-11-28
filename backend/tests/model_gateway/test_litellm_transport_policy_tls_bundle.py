"""Transport trust boundary: the environment gets no vote."""

from __future__ import annotations

import hashlib
import os
import ssl

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.services.model_gateway.litellm import LiteLLMGatewayError
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_CONFIGURATION_INVALID
from app.services.model_gateway.litellm.transport_codes import (
    MAX_CA_BUNDLE_BYTES,
    TLS_DENIAL_BUNDLE_CONTAINS_PRIVATE_KEY,
    TLS_DENIAL_BUNDLE_MATERIAL_CHANGED,
    TLS_DENIAL_BUNDLE_NO_CERTIFICATE,
    TLS_DENIAL_BUNDLE_NOT_A_FILE,
    TLS_DENIAL_BUNDLE_PATH_MISSING,
    TLS_DENIAL_BUNDLE_TOO_LARGE,
    TLS_MODE_PRIVATE_CA_BUNDLE,
)
from app.services.model_gateway.litellm.transport_decisions import TlsTrustPolicy
from tests.model_gateway.conftest import BASE_URL, gateway_section, write_ca_bundle
from tests.model_gateway.litellm_transport_policy_support import private_ca_bundle, resolve


def private_key_pem() -> bytes:
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def test_a_private_ca_bundle_trusts_only_the_configured_certificates(tmp_path) -> None:
    bundle = private_ca_bundle(tmp_path)
    resolution = resolve(BASE_URL, gateway_section(tls={"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)}))

    policy = resolution.policy
    assert policy is not None
    assert policy.tls.mode == TLS_MODE_PRIVATE_CA_BUNDLE
    assert policy.tls.certificate_count == 1
    assert len(policy.tls.bundle_sha256) == 64
    context = policy.tls.ssl_context()
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    # Exactly the configured certificate: the public bundle is not merged in.
    loaded = context.get_ca_certs()
    assert len(loaded) == 1
    assert len(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).get_ca_certs()) == 0
    assert loaded[0]["subject"][0][0][1] == "Octryx Test CA"


def test_ambient_ssl_cert_variables_do_not_change_the_trust_store(tmp_path, monkeypatch) -> None:
    bundle = private_ca_bundle(tmp_path)
    # A second, unrelated CA the ambient variables point at. If any of them were
    # consulted, the trust store below would hold two certificates, not one.
    foreign = private_ca_bundle(tmp_path, name="foreign.pem")
    monkeypatch.setenv("SSL_CERT_FILE", str(foreign))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(foreign))

    resolution = resolve(BASE_URL, gateway_section(tls={"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)}))
    context = resolution.policy.tls.ssl_context()

    assert len(context.get_ca_certs()) == 1


def test_a_replaced_bundle_is_validated_again(tmp_path) -> None:
    bundle = private_ca_bundle(tmp_path)
    section = gateway_section(tls={"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)})
    first = resolve(BASE_URL, section).policy.tls.bundle_sha256

    # Same path, different content: the digest must change, and a bundle that now
    # carries a private key must be refused instead of served from the cache.
    replaced = private_ca_bundle(tmp_path, name="replacement.pem")
    bundle.write_bytes(replaced.read_bytes())
    second = resolve(BASE_URL, section).policy.tls.bundle_sha256
    assert second != first

    bundle.write_bytes(bundle.read_bytes() + private_key_pem())
    refused = resolve(BASE_URL, section)
    assert refused.policy is None
    assert refused.denial_reason == TLS_DENIAL_BUNDLE_CONTAINS_PRIVATE_KEY


def test_the_public_bundle_mode_also_needs_an_explicit_path(tmp_path) -> None:
    missing_path = resolve(BASE_URL, gateway_section(tls={"mode": "public_ca_bundle"}))
    assert missing_path.policy is None
    assert missing_path.denial_reason == TLS_DENIAL_BUNDLE_PATH_MISSING

    bundle = private_ca_bundle(tmp_path, name="public-roots.pem")
    resolution = resolve(
        BASE_URL, gateway_section(tls={"mode": "public_ca_bundle", "ca_bundle_path": str(bundle)})
    )

    policy = resolution.policy
    assert policy is not None
    assert policy.tls.ca_bundle_path == str(bundle.resolve())
    assert policy.tls.certificate_count == 1
    assert len(policy.tls.ssl_context().get_ca_certs()) == 1


def test_the_trust_store_is_built_from_the_validated_bytes_not_from_the_path(tmp_path) -> None:
    bundle = private_ca_bundle(tmp_path)
    policy = resolve(
        BASE_URL, gateway_section(tls={"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)})
    ).policy
    assert policy is not None
    validated_digest = policy.tls.bundle_sha256

    write_ca_bundle(bundle, common_name="Replacement CA")
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() != validated_digest

    loaded = policy.tls.ssl_context().get_ca_certs()

    assert [entry["subject"][0][0][1] for entry in loaded] == ["Octryx Test CA"]
    assert policy.tls.bundle_sha256 == validated_digest


def test_material_that_no_longer_matches_the_validated_digest_is_refused(tmp_path) -> None:
    bundle = private_ca_bundle(tmp_path)
    stale = TlsTrustPolicy(TLS_MODE_PRIVATE_CA_BUNDLE, str(bundle), 1, "0" * 64)

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        stale.ssl_context()

    assert excinfo.value.gateway_state == GATEWAY_STATE_CONFIGURATION_INVALID
    assert excinfo.value.denial_reason == TLS_DENIAL_BUNDLE_MATERIAL_CHANGED
    assert str(bundle) not in str(excinfo.value)


def test_a_bundle_that_became_a_credential_store_is_refused_on_reload(tmp_path) -> None:
    bundle = private_ca_bundle(tmp_path)
    bundle.write_bytes(private_key_pem())
    stale = TlsTrustPolicy(TLS_MODE_PRIVATE_CA_BUNDLE, str(bundle), 1, "0" * 64)

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        stale.ssl_context()

    # The file checks run before the digest comparison, so the operator is told
    # what is actually wrong with the file rather than only that it changed.
    assert excinfo.value.denial_reason == TLS_DENIAL_BUNDLE_CONTAINS_PRIVATE_KEY


def test_an_incomplete_certificate_block_is_not_a_certificate(tmp_path) -> None:
    bundle = private_ca_bundle(tmp_path)
    complete = bundle.read_text()
    bundle.write_text(complete[: complete.index("-----END CERTIFICATE-----")])

    resolution = resolve(
        BASE_URL, gateway_section(tls={"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)})
    )

    assert resolution.policy is None
    assert resolution.denial_reason == TLS_DENIAL_BUNDLE_NO_CERTIFICATE


def test_a_bundle_holding_a_private_key_is_refused(tmp_path) -> None:
    bundle = private_ca_bundle(tmp_path, name="mixed.pem")
    bundle.write_bytes(bundle.read_bytes() + private_key_pem())

    resolution = resolve(BASE_URL, gateway_section(tls={"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)}))

    assert resolution.policy is None
    assert resolution.denial_reason == TLS_DENIAL_BUNDLE_CONTAINS_PRIVATE_KEY


# The bundle is read twice in the lifetime of a policy: once at validation and
# once on the reload path, when a context outlives its cache. Both reads must be
# bounded and must touch a regular file only — a ``stat``-then-``read`` pair is
# neither, because ``st_size`` is meaningless for a FIFO or a device and a
# regular file can grow between the two calls.


def test_a_fifo_at_the_bundle_path_is_refused_instead_of_read(tmp_path) -> None:
    fifo = tmp_path / "ca.pem"
    os.mkfifo(fifo)

    resolution = resolve(
        BASE_URL, gateway_section(tls={"mode": "private_ca_bundle", "ca_bundle_path": str(fifo)})
    )

    assert resolution.policy is None
    assert resolution.denial_reason == TLS_DENIAL_BUNDLE_NOT_A_FILE


def test_a_bundle_path_that_became_a_fifo_is_refused_on_reload(tmp_path) -> None:
    bundle = private_ca_bundle(tmp_path)
    policy = resolve(
        BASE_URL, gateway_section(tls={"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)})
    ).policy
    assert policy is not None
    stale = TlsTrustPolicy(TLS_MODE_PRIVATE_CA_BUNDLE, policy.tls.ca_bundle_path, 1, "0" * 64)
    bundle.unlink()
    os.mkfifo(bundle)

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        stale.ssl_context()

    assert excinfo.value.denial_reason == TLS_DENIAL_BUNDLE_NOT_A_FILE
    assert str(bundle) not in str(excinfo.value)


def test_a_bundle_larger_than_the_bound_is_never_read_whole(tmp_path) -> None:
    oversized = tmp_path / "oversized.pem"
    oversized.write_bytes(b"-----BEGIN CERTIFICATE-----\n" + b"a" * MAX_CA_BUNDLE_BYTES)
    stale = TlsTrustPolicy(TLS_MODE_PRIVATE_CA_BUNDLE, str(oversized), 1, "0" * 64)

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        stale.ssl_context()

    assert excinfo.value.denial_reason == TLS_DENIAL_BUNDLE_TOO_LARGE
