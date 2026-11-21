"""Public Kubernetes CA trust is verified at the real tool and connector-test transport seams."""
from __future__ import annotations

import ssl
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.services.connector_test.incident import test_kubernetes_connection as check_connection
from app.services.named_connections.descriptor import UnitIncompleteError
from app.services.named_connections.descriptors.kubernetes import KUBERNETES
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.tool_routing import routed_execute
from app.tools import kubernetes
from app.tools.context import ToolContext
from app.tools.kubernetes_transport import KubernetesTLSConfigurationError, kubernetes_tls_verify


@pytest.fixture(scope="module")
def public_ca():
    # Generated fixture key stays in memory; no actual cluster credential or trust store is read or changed.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Acceptance fixture CA")])
    now = datetime.now(UTC)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(17).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                   .sign(key, hashes.SHA256()))
    return certificate.public_bytes(serialization.Encoding.PEM).decode()


def context(config):
    return ToolContext(user_id="fixture", project_ids=["workspace"], roles=["admin"], session_id="fixture",
                       project_config=config)


def test_explicit_pem_builds_a_real_isolated_verified_context_without_ambient_trust(public_ca, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/does-not-exist/ambient.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/does-not-exist/ambient")
    verify = kubernetes_tls_verify({"k8s_ca_certificate": public_ca})
    assert isinstance(verify, ssl.SSLContext)
    assert verify.verify_mode == ssl.CERT_REQUIRED and verify.check_hostname
    assert verify.cert_store_stats()["x509_ca"] == 1
    assert verify.get_ca_certs()[0]["serialNumber"] == "11"


@pytest.mark.parametrize("value", ["not a PEM", "-----BEGIN CERTIFICATE-----\nAA==\n-----END CERTIFICATE-----",
                                  "/tmp/cert.pem", "-----BEGIN PRIVATE KEY-----\nprivate\n-----END PRIVATE KEY-----", 42])
def test_malformed_ca_is_refused_without_echoing_the_supplied_material(value):
    with pytest.raises(KubernetesTLSConfigurationError) as error:
        kubernetes_tls_verify({"k8s_ca_certificate": value})
    assert str(value) not in str(error.value)


def test_explicit_ca_never_disables_certificate_or_hostname_verification(public_ca):
    with pytest.raises(KubernetesTLSConfigurationError):
        kubernetes_tls_verify({"k8s_ca_certificate": public_ca, "k8s_verify_tls": False})


@pytest.mark.parametrize("config, expected", [({}, True), ({"k8s_verify_tls": False}, False),
                                            ({"k8s_ca_certificate": " "}, True)])
def test_missing_pem_preserves_existing_flags_and_known_incluster_ca(config, expected):
    assert kubernetes_tls_verify(config) is expected
    assert kubernetes_tls_verify(config, in_cluster_ca="/fixture/sa/ca.crt") == "/fixture/sa/ca.crt"


async def test_named_typed_pod_read_uses_the_ca_on_the_pinned_api_namespace_and_token(public_ca, monkeypatch):
    seen, contexts = [], []
    def response(request):
        seen.append((str(request.url), request.headers.get("Authorization")))
        return httpx.Response(200, json={"items": []})
    def transport(verify):
        contexts.append(verify)
        return httpx.MockTransport(response)
    monkeypatch.setattr(kubernetes, "_k8s_transport", transport)
    named = ResolvedNamedConnection("id", "kubernetes", "cluster", "workspace", frozenset({"cluster"}), {
        "k8s_api_url": "https://cluster.invalid", "k8s_token": "fixture-token", "k8s_ca_certificate": public_ca,
        "k8s_allowed_namespaces": ["allowed"], "k8s_verify_tls": True})
    cfg = {"kubeconfig_path": "/unrelated", NAMED_CONNECTIONS_KEY: NamedConnectionRoutes((named,))}
    result = await routed_execute("list_k8s_pods", {"namespace": "allowed", "cluster": "cluster"},
                                  context(cfg), kubernetes.ListPods().execute)
    assert result["pods"] == []
    assert seen == [("https://cluster.invalid/api/v1/namespaces/allowed/pods", "Bearer fixture-token")]
    assert contexts[0].check_hostname and contexts[0].verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize("config", [{"k8s_ca_certificate": "malformed"},
                                   {"k8s_ca_certificate": "malformed", "k8s_verify_tls": False}])
async def test_bad_ca_refuses_typed_api_and_health_probe_before_transport_creation(config, monkeypatch):
    import app.services.connector_test.incident as incident
    cfg = {"k8s_api_url": "https://cluster.invalid", "k8s_token": "fixture-token", **config}
    def never(*args, **kwargs):
        raise AssertionError("network must never be reached")
    monkeypatch.setattr(kubernetes, "_k8s_transport", never)
    with pytest.raises(KubernetesTLSConfigurationError):
        await kubernetes.ListPods().execute({"namespace": "allowed"}, context(cfg))
    monkeypatch.setattr(incident, "egress_transport", never)
    # The TLS helper runs before either the HTTP client or its transport is created.
    with pytest.raises(KubernetesTLSConfigurationError):
        await check_connection(cfg, httpx_module=SimpleNamespace(AsyncClient=never))


async def test_health_probe_uses_the_same_verified_context(public_ca, monkeypatch):
    import app.services.connector_test.incident as incident
    seen = []
    def response(request):
        assert request.headers["authorization"] == "Bearer fixture-token"
        return httpx.Response(200, json={"gitVersion": "v1.34.1"})
    def transport(connection, *, verify):
        seen.append(verify)
        return httpx.MockTransport(response)
    monkeypatch.setattr(incident, "egress_transport", transport)
    result = await check_connection({"k8s_api_url": "https://cluster.invalid", "k8s_token": "fixture-token",
                                     "k8s_ca_certificate": public_ca}, httpx_module=httpx)
    assert result["ok"]
    assert seen[0].check_hostname and seen[0].verify_mode == ssl.CERT_REQUIRED


def test_named_descriptor_public_ca_field_and_pre_call_guard(public_ca):
    field = next(field for field in KUBERNETES.fields if field.name == "k8s_ca_certificate")
    assert not field.secret and not field.required
    KUBERNETES.runtime_guard({"k8s_api_url": "https://cluster.invalid", "k8s_token": "fixture-token",
                              "k8s_ca_certificate": public_ca})
    with pytest.raises(UnitIncompleteError) as error:
        KUBERNETES.runtime_guard({"k8s_api_url": "https://cluster.invalid", "k8s_token": "fixture-token",
                                  "k8s_ca_certificate": "bad"})
    assert error.value.code == "kubernetes_tls_not_configured"

async def test_public_pem_roundtrips_in_named_fields_while_token_stays_write_only(db, public_ca):
    from app.services.admin.project.named_connection_service import save_named
    from app.services.admin.project.named_connection_view import list_named
    from tests.knowledge_evidence_seed_support import seed_workspace
    workspace = await seed_workspace(db)
    saved = await save_named(db, connector="kubernetes", project_id=workspace, actor_id=None, payload={
        "name": "fixture-cluster", "bound_scopes": ["fixture-cluster"], "k8s_api_url": "https://cluster.invalid",
        "k8s_token": "fixture-token", "k8s_verify_tls": True, "k8s_ca_certificate": public_ca})
    assert saved["fields"]["k8s_ca_certificate"] == public_ca.strip()
    listed = await list_named(db, connector="kubernetes", project_id=workspace)
    assert "fixture-token" not in str(listed)
    assert "k8s_ca_certificate" in str(listed)
