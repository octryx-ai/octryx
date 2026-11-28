"""The uncredentialed public web fetch: pinned like every credentialed client."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx

from ..outbound_url_policy import CheckedTarget, OutboundURLPolicyError
from .connections import CONNECTION_PUBLIC_WEB
from .pinned_transport import _LIMITS, EgressRefusedError, PinnedEgressTransport

MAX_REDIRECTS = 5
REASON_PROXY_INVALID = "web_fetch_proxy_invalid"
REASON_NOT_GLOBAL_ADDRESS = "not_global_address"


class _ProxiedHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self, proxy_url: str, *, network_backend: httpcore.AsyncNetworkBackend | None) -> None:
        proxy = httpx.Proxy(proxy_url)
        self._pool = httpcore.AsyncHTTPProxy(
            proxy_url=httpcore.URL(
                scheme=proxy.url.raw_scheme,
                host=proxy.url.raw_host,
                port=proxy.url.port,
                target=proxy.url.raw_path,
            ),
            proxy_auth=proxy.raw_auth,
            proxy_headers=proxy.headers.raw,
            ssl_context=httpx.create_ssl_context(verify=True),
            max_connections=_LIMITS.max_connections,
            max_keepalive_connections=_LIMITS.max_keepalive_connections,
            keepalive_expiry=_LIMITS.keepalive_expiry,
            network_backend=network_backend,
        )


def configured_proxy_url() -> str | None:
    from ...config import get_settings

    raw = str(get_settings().web_fetch_proxy_url or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        port_ok = parts.port is None or 0 < parts.port < 65536
    except ValueError:
        raise EgressRefusedError(REASON_PROXY_INVALID) from None
    if parts.scheme not in {"http", "https"} or not parts.hostname or not port_ok:
        raise EgressRefusedError(REASON_PROXY_INVALID)
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise EgressRefusedError(REASON_PROXY_INVALID)
    return raw


def require_globally_routable(target: CheckedTarget) -> None:
    for raw in target.addresses:
        address = ipaddress.ip_address(raw)
        reached = [address]
        if address.version == 6:
            reached += [embedded for embedded in (address.ipv4_mapped, address.sixtofour) if embedded is not None]
        if any(not item.is_global or item.is_multicast for item in reached):
            raise OutboundURLPolicyError("Outbound address is not globally routable", reason=REASON_NOT_GLOBAL_ADDRESS)


def public_web_transport(
    *,
    network_backend: httpcore.AsyncNetworkBackend | None = None,
    globally_routable_only: bool = False,
) -> PinnedEgressTransport:
    target_rule = require_globally_routable if globally_routable_only else None
    proxy_url = configured_proxy_url()
    if proxy_url is None:
        return PinnedEgressTransport(CONNECTION_PUBLIC_WEB, network_backend=network_backend, target_rule=target_rule)
    return PinnedEgressTransport(
        CONNECTION_PUBLIC_WEB,
        inner=_ProxiedHTTPTransport(proxy_url, network_backend=network_backend),
        target_rule=target_rule,
    )


def public_web_client(
    *,
    timeout: Any,
    headers: dict[str, str] | None = None,
    network_backend: httpcore.AsyncNetworkBackend | None = None,
    globally_routable_only: bool = False,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    transport = public_web_transport(network_backend=network_backend, globally_routable_only=globally_routable_only)
    return httpx.AsyncClient(
        timeout=timeout,
        headers=headers,
        follow_redirects=follow_redirects,
        max_redirects=MAX_REDIRECTS,
        trust_env=False,
        transport=transport,
    )


__all__ = [
    "MAX_REDIRECTS",
    "REASON_NOT_GLOBAL_ADDRESS",
    "REASON_PROXY_INVALID",
    "configured_proxy_url",
    "public_web_client",
    "public_web_transport",
    "require_globally_routable",
]
