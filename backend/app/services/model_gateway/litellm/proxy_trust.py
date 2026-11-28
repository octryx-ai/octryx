"""Explicit trust decision for the governed proxy's own TLS leg (Issue)."""

from __future__ import annotations

# How the proxy's own TLS leg is trusted. Recorded in evidence, so a report says
# which decision was taken rather than leaving it to be inferred.
PROXY_TLS_TRUST_NOT_APPLICABLE = "not_applicable"
PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE = "gateway_ca_bundle"
PROXY_TLS_TRUST_SOURCES = frozenset({PROXY_TLS_TRUST_NOT_APPLICABLE, PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE})

PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED = "proxy_tls_trust_not_configured"


def resolve_proxy_tls_trust(*, proxy_scheme: str, gateway_trust_store_validated: bool) -> tuple[str, str]:
    if str(proxy_scheme).strip().lower() != "https":
        return PROXY_TLS_TRUST_NOT_APPLICABLE, ""
    if not gateway_trust_store_validated:
        return "", PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED
    return PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE, ""


__all__ = [
    "PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED",
    "PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE",
    "PROXY_TLS_TRUST_NOT_APPLICABLE",
    "PROXY_TLS_TRUST_SOURCES",
    "resolve_proxy_tls_trust",
]
