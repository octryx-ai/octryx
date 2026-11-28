"""Validated transport decisions: the trust store, the egress hop and the httpx arguments built from them."""

from __future__ import annotations

import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .ca_bundle import _SSL_CONTEXTS, _read_certificate_material, _trust_store_from_cadata
from .errors import GATEWAY_STATE_CONFIGURATION_INVALID, LiteLLMGatewayError
from .proxy_trust import (
    PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED,
)
from .transport_codes import (
    PLAINTEXT_TLS_MODES,
    PROXY_DENIAL_CLUSTER_INTERNAL_REQUIRES_DIRECT,
    PROXY_MODE_GOVERNED,
    TLS_DENIAL_BUNDLE_MATERIAL_CHANGED,
    TLS_DENIAL_BUNDLE_NOT_LOADABLE,
    TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL,
)


@dataclass(frozen=True, slots=True)
class TlsTrustPolicy:
    mode: str
    ca_bundle_path: str
    certificate_count: int
    bundle_sha256: str
    # ``plaintext_cluster_internal`` only: the operator's attestation of what protects the clear-text hop.
    node_encryption: str = ""
    attestation_reference: str = ""
    attested_on: str = ""

    @property
    def plaintext(self) -> bool:
        return self.mode in PLAINTEXT_TLS_MODES

    @property
    def cluster_internal(self) -> bool:
        return self.mode == TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL

    def ssl_context(self) -> ssl.SSLContext | None:
        if self.plaintext:
            return None
        key = (self.ca_bundle_path, self.bundle_sha256)
        cached = _SSL_CONTEXTS.get(key)
        if cached is not None:
            return cached
        # Reached only when the context is no longer cached; the digest is the contract, so no trust store is built
        # from material that no longer hashes to it.
        cadata, _count, digest, denial, _identity = _read_certificate_material(self.ca_bundle_path)
        if denial or digest != self.bundle_sha256:
            raise LiteLLMGatewayError(
                GATEWAY_STATE_CONFIGURATION_INVALID,
                denial_reason=denial or TLS_DENIAL_BUNDLE_MATERIAL_CHANGED,
            ) from None
        context = _trust_store_from_cadata(cadata)
        if context is None:
            raise LiteLLMGatewayError(
                GATEWAY_STATE_CONFIGURATION_INVALID,
                denial_reason=TLS_DENIAL_BUNDLE_NOT_LOADABLE,
            ) from None
        _SSL_CONTEXTS[key] = context
        return context

    def evidence(self) -> dict[str, Any]:
        # The bundle digest is public certificate material, not a secret, and it
        # is what makes "which trust store was this qualified against" auditable.
        payload: dict[str, Any] = {
            "tls_mode": self.mode,
            "tls_ca_bundle_certificate_count": self.certificate_count,
            "tls_ca_bundle_sha256": self.bundle_sha256,
        }
        if self.cluster_internal:
            # What stands in for TLS on this hop is an operator statement, and it
            # is recorded as one — never as a certificate count or a digest.
            payload.update(
                {
                    "tls_node_encryption": self.node_encryption,
                    "tls_attestation_reference": self.attestation_reference,
                    "tls_attested_on": self.attested_on,
                }
            )
        return payload


@dataclass(frozen=True, slots=True)
class GovernedProxy:
    mode: str
    scheme: str = ""
    host: str = ""
    port: int | None = None
    # How the proxy's own TLS leg is trusted (``proxy_trust``); empty on the direct path.
    tls_trust_source: str = ""

    @property
    def governed(self) -> bool:
        return self.mode == PROXY_MODE_GOVERNED

    @property
    def tls_leg(self) -> bool:
        return self.governed and self.scheme == "https"

    @property
    def url(self) -> str:
        if not self.governed:
            return ""
        authority = self.host if self.port is None else f"{self.host}:{self.port}"
        return f"{self.scheme}://{authority}"

    def evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"proxy_mode": self.mode}
        if self.governed:
            payload.update(
                {
                    "proxy_scheme": self.scheme,
                    "proxy_host": self.host,
                    "proxy_port": self.port,
                    "proxy_tls_trust_source": self.tls_trust_source,
                }
            )
        return payload


@dataclass(frozen=True, slots=True)
class TransportPolicy:
    tls: TlsTrustPolicy
    proxy: GovernedProxy

    def httpx_client_kwargs(self) -> dict[str, Any]:
        """The transport arguments the gateway client must construct httpx with."""

        context = self.tls.ssl_context()
        if context is None and self.proxy.tls_leg:
            # Backstop for ``proxy_trust``: httpx verifies the proxy with this argument, so ``False`` would tunnel the
            # virtual key through an unverified peer.
            raise LiteLLMGatewayError(
                GATEWAY_STATE_CONFIGURATION_INVALID,
                denial_reason=PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED,
            ) from None
        if self.tls.cluster_internal and self.proxy.governed:
            # Backstop for ``_resolve_proxy``: a cluster-internal plaintext hop is direct only.
            raise LiteLLMGatewayError(
                GATEWAY_STATE_CONFIGURATION_INVALID,
                denial_reason=PROXY_DENIAL_CLUSTER_INTERNAL_REQUIRES_DIRECT,
            ) from None
        return {
            # ``False`` only for a plaintext ``http`` endpoint: no TLS leg to verify, and no TLS proxy leg (see above).
            "verify": False if context is None else context,
            "proxy": self.proxy.url or None,
            # The environment gets no vote on trust store, proxy or credentials.
            "trust_env": False,
        }

    def evidence(self) -> dict[str, Any]:
        return {**self.tls.evidence(), **self.proxy.evidence()}


@dataclass(frozen=True, slots=True)
class TransportPolicyResolution:
    policy: TransportPolicy | None
    denial_reason: str = ""
    # Present only when a private bundle was read, so callers can report the count without re-reading the file.
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.policy is not None
