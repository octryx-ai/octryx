"""Admission of the optional governed egress proxy for the LiteLLM gateway (``transport_policy``).

Every rejection is a fixed reason code; the configured URL is never echoed, since an operator can paste a
credential into it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from .endpoint import ENDPOINT_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED, GatewayEndpoint, normalize_host_allowlist
from .proxy_trust import resolve_proxy_tls_trust
from .transport_codes import (
    PROXY_DENIAL_CLUSTER_INTERNAL_REQUIRES_DIRECT,
    PROXY_DENIAL_CONTRACT_MALFORMED,
    PROXY_DENIAL_FRAGMENT_PRESENT,
    PROXY_DENIAL_HOST_ALLOWLIST_INVALID,
    PROXY_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED,
    PROXY_DENIAL_HOST_MISSING,
    PROXY_DENIAL_HOST_NOT_ALLOWLISTED,
    PROXY_DENIAL_MODE_UNKNOWN,
    PROXY_DENIAL_PLAINTEXT_REQUIRES_TLS_ENDPOINT,
    PROXY_DENIAL_QUERY_PRESENT,
    PROXY_DENIAL_SCHEME_NOT_SUPPORTED,
    PROXY_DENIAL_UNEXPECTED_PATH,
    PROXY_DENIAL_URL_NOT_CONFIGURED,
    PROXY_DENIAL_URL_UNPARSABLE,
    PROXY_DENIAL_USERINFO_PRESENT,
    PROXY_MODE_DIRECT,
    PROXY_MODE_GOVERNED,
    PROXY_MODES,
)
from .transport_decisions import GovernedProxy

_PROXY_SCHEMES = frozenset({"https", "http"})
_PROXY_ALLOWED_PATHS = frozenset({"", "/"})
_DEFAULT_PORTS = {"https": 443, "http": 80}


def _resolve_proxy(
    raw: Any,
    *,
    endpoint: GatewayEndpoint,
    gateway_trust_store_validated: bool,
    direct_only: bool = False,
) -> tuple[GovernedProxy | None, str]:
    if raw is None:
        # No proxy section means the explicit direct path, not "inherit
        # whatever the environment says" — httpx runs with trust_env=False.
        return GovernedProxy(PROXY_MODE_DIRECT), ""
    if not isinstance(raw, Mapping):
        return None, PROXY_DENIAL_CONTRACT_MALFORMED
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in PROXY_MODES:
        return None, PROXY_DENIAL_MODE_UNKNOWN
    if mode == PROXY_MODE_DIRECT:
        return GovernedProxy(PROXY_MODE_DIRECT), ""
    if direct_only:
        # A cluster-internal plaintext hop sends the virtual key in clear; adding
        # an egress hop would carry it beyond the attested pod network.
        return None, PROXY_DENIAL_CLUSTER_INTERNAL_REQUIRES_DIRECT

    hosts, allowlist_denial = normalize_host_allowlist(raw.get("host_allowlist"))
    if allowlist_denial:
        return None, (
            PROXY_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED
            if allowlist_denial == ENDPOINT_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED
            else PROXY_DENIAL_HOST_ALLOWLIST_INVALID
        )
    target, url_denial = _proxy_target(raw.get("url"), hosts=hosts, endpoint=endpoint)
    if target is None:
        return None, url_denial
    scheme, normalized_host, port = target
    # The proxy's own TLS leg is a separate trust decision, taken explicitly
    # rather than inherited from whatever the gateway leg happens to use.
    trust_source, trust_denial = resolve_proxy_tls_trust(
        proxy_scheme=scheme,
        gateway_trust_store_validated=gateway_trust_store_validated,
    )
    if trust_denial:
        return None, trust_denial
    return (
        GovernedProxy(
            PROXY_MODE_GOVERNED,
            scheme,
            normalized_host,
            port or _DEFAULT_PORTS[scheme],
            tls_trust_source=trust_source,
        ),
        "",
    )


def _proxy_target(
    candidate: Any, *, hosts: Any, endpoint: GatewayEndpoint
) -> tuple[tuple[str, str, int | None] | None, str]:
    """Validate the proxy URL against the allowlist; returns ``((scheme, host, port), "")`` or a denial."""

    candidate = candidate.strip() if isinstance(candidate, str) else ""
    if not candidate:
        return None, PROXY_DENIAL_URL_NOT_CONFIGURED
    try:
        parts = urlsplit(candidate)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None, PROXY_DENIAL_URL_UNPARSABLE

    scheme = parts.scheme.strip().lower()
    if scheme not in _PROXY_SCHEMES:
        return None, PROXY_DENIAL_SCHEME_NOT_SUPPORTED
    if parts.username or parts.password:
        # Proxy credentials in product configuration would be a second, ungoverned
        # secret store. A credentialed proxy needs a Secret Reference contract.
        return None, PROXY_DENIAL_USERINFO_PRESENT
    if parts.query:
        return None, PROXY_DENIAL_QUERY_PRESENT
    if parts.fragment:
        return None, PROXY_DENIAL_FRAGMENT_PRESENT
    if parts.path not in _PROXY_ALLOWED_PATHS:
        return None, PROXY_DENIAL_UNEXPECTED_PATH
    if not host:
        return None, PROXY_DENIAL_HOST_MISSING
    normalized_host = host.strip().lower()
    if normalized_host not in hosts:
        return None, PROXY_DENIAL_HOST_NOT_ALLOWLISTED
    if scheme == "http" and endpoint.scheme != "https":
        # A plaintext hop is admitted only when the gateway leg is TLS, so the
        # virtual key stays inside the CONNECT tunnel.
        return None, PROXY_DENIAL_PLAINTEXT_REQUIRES_TLS_ENDPOINT
    return (scheme, normalized_host, port), ""


def default_port_for_scheme(scheme: str) -> int | None:
    return _DEFAULT_PORTS.get(scheme)
