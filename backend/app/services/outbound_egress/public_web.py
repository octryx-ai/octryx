"""The uncredentialed public web fetch: pinned like every credentialed client.

The web fetch tool, the knowledge URL fetch, document-source ingestion and the workspace HTTP
request tool build their client with :func:`public_web_client`. Its transport is the pinned
egress transport of the ``public_web`` connection (``public_only``, no private-host allowlist):
each request and each redirect hop is checked once, and the connection goes only to the checked
address, so a DNS answer that changes after the check (rebinding) is never connected.

Proxies are explicit. Environment proxies (``HTTP_PROXY``, ``HTTPS_PROXY``, ``ALL_PROXY``,
``NO_PROXY``) are never read (``trust_env=False``). A forward proxy is used only when the runtime
setting ``OCTRYX_WEB_FETCH_PROXY_URL`` names one (``http://proxy.corp.example:3128``;
unset by default). With a proxy, every target is still checked before the request is sent, and the
request then goes to the named proxy, which resolves and connects the target itself: pinning the
target's address is then the proxy's responsibility. A setting that is not an ``http``/``https``
URL with a host (and no path, query or fragment) refuses every fetch with
``web_fetch_proxy_invalid``; it never falls back to a direct connection.

``globally_routable_only`` adds a stricter address rule on top of ``public_only`` (the research
package fetch, ``knowledge/sources/web_fetch.py``): every checked address, and the IPv4 address an
IPv6 transition form reaches, must be globally routable and not multicast, so documentation,
benchmarking, reserved and shared ranges are refused too (``not_global_address``). It is checked
on the same single resolution the connection is pinned to.
"""

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
    """``httpx``'s request mapping over a pool that sends through the named forward proxy.

    Like the pinned pool, the parent initializer is not run; ``network_backend`` is the socket
    layer under the pool (a test seam for the connect address).
    """

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
    """The admin-named web fetch proxy, ``None`` when unset; an unusable value is refused."""
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
    """Refuse a target any of whose addresses is not globally routable (``not_global_address``)."""
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
    """The pinned ``public_web`` transport; through the named proxy when one is configured."""
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
    """The client of every uncredentialed web fetch: pinned, redirect-bounded, no environment proxy.

    ``network_backend`` replaces the socket layer (a test seam); it cannot skip the check. A caller
    that follows redirects by hand passes ``follow_redirects=False``; each hop is still checked.
    """
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
