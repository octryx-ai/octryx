"""Explicit transport trust policy for the governed LiteLLM gateway client.

The transport boundary is part of the credential boundary: the
``Authorization: Bearer <virtual key>`` header travels over whatever trust store
and whatever proxy the transport was built with. ``client.py`` therefore runs
httpx with ``trust_env=False``, which removes ``HTTP_PROXY``, ``HTTPS_PROXY``,
``ALL_PROXY``, ``NO_PROXY``, ``SSL_CERT_FILE``, ``SSL_CERT_DIR`` and ``.netrc``
from the picture. This module supplies the governed alternative so that removal
does not leave an internal deployment without a usable option:

``config_json["litellm_gateway"]["tls"]``
    ``{"mode": "private_ca_bundle", "ca_bundle_path": "/etc/octryx/ca/internal.pem"}``
        Trust exactly the certificates in that file and nothing else.
    ``{"mode": "public_ca_bundle", "ca_bundle_path": "/etc/ssl/certs/ca-certificates.crt"}``
        Trust exactly the certificates in that public root-program bundle. The
        path is explicit for the same reason the private one is: OpenSSL's
        default paths — and therefore ``SSL_CERT_FILE``/``SSL_CERT_DIR`` — are
        never consulted, and the recorded bundle digest stays auditable. The mode
        only records the operator's statement about *what kind* of anchor set the
        file holds; both modes are validated and digested identically.
    ``{"mode": "plaintext_loopback"}``
        Admitted only for an ``http`` loopback endpoint (local fixture / dev).
    ``{"mode": "plaintext_cluster_internal", "node_encryption": "wireguard",
       "attested_on": "2026-11-06", "attestation_reference": "cluster-attestation-2026-11-06"}``
        "Cluster-internal": admitted only for an ``http`` endpoint whose host is a
        fully qualified Kubernetes Service name (``<svc>.<ns>.svc.cluster.local``,
        exact suffix, no IP, no ``.svc`` short form) that is also on the host
        allowlist, and only with the operator's attestation that node-to-node
        traffic is encrypted underneath (``node_encryption``; ``wireguard`` is the
        one admitted value). The virtual key travels in clear on the pod network,
        so this is *declared* transport protection, not a verified TLS chain:
        evidence records ``tls_mode``, ``tls_node_encryption`` and the
        attestation, and the qualification report states the transport assurance
        as operator-attested. No governed proxy is admitted with this mode — the
        only path is direct.

``config_json["litellm_gateway"]["proxy"]`` (optional)
    ``{"mode": "direct"}`` or
    ``{"mode": "governed_proxy", "url": "https://egress.internal:3128",
       "host_allowlist": ["egress.internal"]}``

    A governed proxy is two connections. The proxy's *own* TLS leg is a separate
    trust decision, taken explicitly in ``proxy_trust`` and recorded as
    ``proxy_tls_trust_source``: an ``https`` proxy is admitted only when a
    validated trust store exists to verify it against, so ``verify=False`` is
    never used for a proxy TLS leg.

Every rejection is a fixed reason code. Neither the configured URL nor an
OpenSSL error string is ever echoed: an operator can paste a credential into a
proxy URL, and an OpenSSL message can carry a filesystem path.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from .ca_bundle import _read_ca_bundle
from .endpoint import (
    GatewayEndpoint,
    is_cluster_internal_service_host,
)
from .proxy_admission import _resolve_proxy
from .transport_codes import (
    NODE_ENCRYPTION_MECHANISMS,
    TLS_DENIAL_ATTESTATION_REFERENCE_MISSING,
    TLS_DENIAL_ATTESTED_ON_INVALID,
    TLS_DENIAL_CONTRACT_MISSING,
    TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT,
    TLS_DENIAL_MODE_UNKNOWN,
    TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED,
    TLS_DENIAL_PLAINTEXT_NOT_CLUSTER_SERVICE,
    TLS_DENIAL_PLAINTEXT_OFF_LOOPBACK,
    TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL,
    TLS_MODE_PLAINTEXT_LOOPBACK,
    TLS_MODES,
)
from .transport_decisions import TlsTrustPolicy, TransportPolicy, TransportPolicyResolution

# Same governance-record charset as the content-logging attestation: it ends up
# in stored evidence.
_ATTESTATION_REFERENCE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _resolve_tls_policy(raw: Any, *, endpoint: GatewayEndpoint) -> tuple[TlsTrustPolicy | None, str]:
    if not isinstance(raw, Mapping):
        return None, TLS_DENIAL_CONTRACT_MISSING
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in TLS_MODES:
        return None, TLS_DENIAL_MODE_UNKNOWN
    if mode == TLS_MODE_PLAINTEXT_LOOPBACK:
        if endpoint.scheme != "http":
            return None, TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT
        if not endpoint.loopback:
            return None, TLS_DENIAL_PLAINTEXT_OFF_LOOPBACK
        return TlsTrustPolicy(mode, "", 0, ""), ""
    if mode == TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL:
        return _resolve_cluster_internal_plaintext(raw, endpoint=endpoint)
    if endpoint.scheme != "https":
        # A trust store is meaningless for a plaintext endpoint, and admitting
        # the pair would hide which one the operator actually meant.
        return None, TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT
    # Both bundle modes take an explicit path: a library-shipped default would be
    # an implicit trust store that changes on dependency upgrade without the
    # recorded digest ever being reviewed.
    path, count, digest, denial = _read_ca_bundle(raw.get("ca_bundle_path"))
    if denial:
        return None, denial
    return TlsTrustPolicy(mode, path, count, digest), ""


def _resolve_cluster_internal_plaintext(
    raw: Mapping[str, Any], *, endpoint: GatewayEndpoint
) -> tuple[TlsTrustPolicy | None, str]:
    """Admit ``plaintext_cluster_internal`` for a cluster Service name, attested.

    The host is re-checked here from ``endpoint.host`` rather than trusted from the
    endpoint's flag, so this rule does not depend on another module's rule (the
    same reasoning as the loopback branch). The host allowlist was already
    enforced by ``validate_gateway_endpoint``.
    """

    if endpoint.scheme != "http":
        # TLS to a cluster Service needs a CA bundle mode, not this one.
        return None, TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT
    if endpoint.loopback or not is_cluster_internal_service_host(endpoint.host):
        return None, TLS_DENIAL_PLAINTEXT_NOT_CLUSTER_SERVICE
    node_encryption = raw.get("node_encryption")
    node_encryption = node_encryption.strip().lower() if isinstance(node_encryption, str) else ""
    if node_encryption not in NODE_ENCRYPTION_MECHANISMS:
        return None, TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED
    reference = str(raw.get("attestation_reference") or "").strip()
    if not _ATTESTATION_REFERENCE_RE.match(reference):
        return None, TLS_DENIAL_ATTESTATION_REFERENCE_MISSING
    attested_on = str(raw.get("attested_on") or "").strip()
    try:
        if date.fromisoformat(attested_on).isoformat() != attested_on:
            raise ValueError
    except ValueError:
        return None, TLS_DENIAL_ATTESTED_ON_INVALID
    return (
        TlsTrustPolicy(
            TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL,
            "",
            0,
            "",
            node_encryption=node_encryption,
            attestation_reference=reference,
            attested_on=attested_on,
        ),
        "",
    )


def declares_cluster_internal_plaintext(section: Any) -> bool:
    """True when the gateway section's ``tls.mode`` is ``plaintext_cluster_internal``.

    Only a *declaration*: it lets ``validate_gateway_endpoint`` admit an ``http``
    cluster Service host far enough for ``resolve_transport_policy`` to judge the
    full contract (host shape, attestation, direct path). It admits nothing on
    its own.
    """

    tls = section.get("tls") if isinstance(section, Mapping) else None
    mode = tls.get("mode") if isinstance(tls, Mapping) else None
    return isinstance(mode, str) and mode.strip().lower() == TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL


def resolve_transport_policy(*, endpoint: GatewayEndpoint, section: Any) -> TransportPolicyResolution:
    """Resolve the governed TLS/proxy transport policy, or a fixed denial code."""

    raw_section = section if isinstance(section, Mapping) else {}
    tls, tls_denial = _resolve_tls_policy(raw_section.get("tls"), endpoint=endpoint)
    if tls is None:
        return TransportPolicyResolution(None, tls_denial)
    proxy, proxy_denial = _resolve_proxy(
        raw_section.get("proxy"),
        endpoint=endpoint,
        # A validated bundle is what the proxy leg can be verified against; a
        # plaintext policy has no trust store to offer it.
        gateway_trust_store_validated=not tls.plaintext,
        direct_only=tls.cluster_internal,
    )
    if proxy is None:
        return TransportPolicyResolution(None, proxy_denial)
    return TransportPolicyResolution(TransportPolicy(tls=tls, proxy=proxy))


__all__ = [
    "declares_cluster_internal_plaintext",
    "resolve_transport_policy",
]
