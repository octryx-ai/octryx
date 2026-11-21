"""Explicit trust decision for the governed proxy's own TLS leg (Issue).

A governed proxy is two connections, and only one of them was governed:

``http`` proxy
    The client speaks ``CONNECT`` to the proxy in clear and the gateway leg is
    TLS inside that tunnel. There is no proxy TLS leg to trust, and the virtual
    key never leaves the tunnel — which is why a plaintext hop is admitted only
    against an ``https`` gateway endpoint (``proxy_admission._resolve_proxy``).

``https`` proxy
    The ``CONNECT`` request itself travels over TLS to the proxy, so the proxy
    presents a certificate of its own. httpx verifies that leg with the same
    ``verify`` argument as the gateway leg, so with a ``plaintext_loopback``
    gateway — where ``verify`` is ``False`` — the proxy certificate was not
    verified at all, while the client still believed it was using a governed
    egress hop.

This module makes that decision explicit instead of inheriting it:

- an ``http`` proxy records ``not_applicable``: there is no TLS leg to trust;
- an ``https`` proxy is admitted only when the client has a validated trust
  store, and records ``gateway_ca_bundle`` — the proxy leg is verified against
  the same explicitly configured, digested anchor set as the gateway leg, so a
  proxy whose issuer is not in that bundle fails the handshake instead of being
  trusted silently. An operator terminating TLS on the proxy with a different
  internal issuer therefore has to add that anchor to the configured bundle;
- an ``https`` proxy without a validated trust store is **refused**
  (``proxy_tls_trust_not_configured``). ``verify=False`` is never used for a
  proxy TLS leg.

A ``plaintext_cluster_internal`` gateway never reaches this decision: that mode
is direct-only and ``transport_policy`` refuses any governed proxy with it
(``proxy_not_permitted_with_cluster_internal_plaintext``).

A separate per-proxy trust contract (its own ``ca_bundle_path`` for the proxy
leg) is deliberately not introduced here; it is a configuration surface of its
own, and this module is the boundary that would own it.
"""

from __future__ import annotations

# How the proxy's own TLS leg is trusted. Recorded in evidence, so a report says
# which decision was taken rather than leaving it to be inferred.
PROXY_TLS_TRUST_NOT_APPLICABLE = "not_applicable"
PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE = "gateway_ca_bundle"
PROXY_TLS_TRUST_SOURCES = frozenset({PROXY_TLS_TRUST_NOT_APPLICABLE, PROXY_TLS_TRUST_GATEWAY_CA_BUNDLE})

PROXY_DENIAL_TLS_TRUST_NOT_CONFIGURED = "proxy_tls_trust_not_configured"


def resolve_proxy_tls_trust(*, proxy_scheme: str, gateway_trust_store_validated: bool) -> tuple[str, str]:
    """Return ``(trust source, denial code)`` for the proxy's own TLS leg.

    ``gateway_trust_store_validated`` is the property that matters — whether the
    client holds an explicit, validated trust store at all — rather than the TLS
    mode name, so this stays independent of the mode enum it would otherwise
    have to import back from ``transport_policy``.
    """

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
