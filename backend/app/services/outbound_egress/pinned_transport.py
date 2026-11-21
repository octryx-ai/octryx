"""A pinned ``httpx`` transport: a credentialed request connects only to the address the policy checked.

A policy check that resolves a hostname and then lets ``httpx`` resolve it again when it
connects is open to DNS rebinding: the second answer may be a pod-local or private address
the first one was not. :class:`PinnedEgressTransport` closes that gap:

1. before every request (each redirect hop is its own request), it checks the target with the
   connection's rule (``target_check.py``), which resolves the hostname **once**;
2. it records the checked addresses for that ``host:port``;
3. its connection pool uses a network backend that connects to a recorded address and never
   resolves anything. A target without a recorded address is refused (``unpinned_target``).

The URL is not rewritten, so the ``Host`` header, TLS SNI and certificate hostname
verification all stay with the original hostname, and pooled connections stay keyed by it.
Environment proxies are not used: a pinned client connects directly. The one proxy is the web
fetch proxy an admin names explicitly (``public_web.py``).

The only loopback exemption is the loopback stub allowlist
(``app/loopback_stub_policy.py``): the transport asks it for its own connection type
on every request, so the stubbed connection types (Confluence, Jira) reach exactly the listed
literal ``host:port`` pairs on a local development stack, and no caller can pass another one.

A refusal raises :class:`EgressRefusedError` before anything is sent. It is an
``httpx.TransportError`` (connectors report a failed call) and an ``OutboundURLPolicyError``
(the fixed ``reason`` stays available); its message names the reason only, never the host.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import httpcore
import httpx

from ...loopback_stub_policy import loopback_stub_exemption
from ..outbound_url_policy import CheckedTarget, OutboundURLPolicyError
from .connections import connection_rule
from .target_check import check_connection_target

REASON_UNPINNED_TARGET = "unpinned_target"
_DEFAULT_PORTS = {"http": 80, "https": 443}
_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0)


class EgressRefusedError(httpx.TransportError, OutboundURLPolicyError):
    """The egress rule refused a credentialed request before it was sent."""

    def __init__(self, reason: str, *, request: httpx.Request | None = None) -> None:
        message = f"egress_refused: {reason}"
        httpx.TransportError.__init__(self, message, request=request)
        self.reason = reason


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connects a ``host:port`` only to an address the transport checked; resolves nothing."""

    def __init__(self, pins: dict[tuple[str, int], tuple[str, ...]], inner: httpcore.AsyncNetworkBackend) -> None:
        self._pins = pins
        self._inner = inner

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = self._pins.get((str(host).lower(), int(port)))
        if not addresses:
            raise httpcore.ConnectError(f"egress_refused: {REASON_UNPINNED_TARGET}")
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as error:
                last_error = error
        raise last_error if last_error is not None else httpcore.ConnectError(REASON_UNPINNED_TARGET)

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None):
        raise httpcore.ConnectError(f"egress_refused: {REASON_UNPINNED_TARGET}")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _PinnedHTTPTransport(httpx.AsyncHTTPTransport):
    """``httpx``'s own request mapping, over a pool whose network backend is the pinned one.

    ``AsyncHTTPTransport`` keeps all its state in ``_pool``; the parent initializer is not run
    because it would build a second, unpinned pool.
    """

    def __init__(self, *, verify: Any, network_backend: httpcore.AsyncNetworkBackend) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=verify),
            max_connections=_LIMITS.max_connections,
            max_keepalive_connections=_LIMITS.max_keepalive_connections,
            keepalive_expiry=_LIMITS.keepalive_expiry,
            network_backend=network_backend,
        )


def _pin_key(url: httpx.URL) -> tuple[str, int]:
    host = url.raw_host.decode("ascii").lower()
    return host, int(url.port or _DEFAULT_PORTS.get(url.scheme, 0))


class PinnedEgressTransport(httpx.AsyncBaseTransport):
    """Checks every request with the connection's egress rule and connects only to checked addresses.

    The loopback stub exemption of the connection type is re-read per request
    (``loopback_stub_exemption``); it is the only exemption and not a parameter. ``inner`` replaces the pinned
    pool with another transport after the check (the named web fetch proxy of ``public_web.py``,
    or a test's recorded responses);
    ``network_backend`` replaces the socket layer under the pinned pool (a test seam for the
    connect address). Neither can skip the check. ``target_rule`` is a caller's stricter rule on
    the checked target (it raises :class:`OutboundURLPolicyError`); it runs after the connection's
    rule and before anything is pinned or sent, on every request and redirect hop.
    """

    def __init__(
        self,
        connection: str,
        *,
        verify: Any = True,
        inner: httpx.AsyncBaseTransport | None = None,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
        target_rule: Callable[[CheckedTarget], None] | None = None,
    ) -> None:
        self._rule = connection_rule(connection)
        self._target_rule = target_rule
        self._pins: dict[tuple[str, int], tuple[str, ...]] = {}
        if inner is None:
            backend = _PinnedNetworkBackend(self._pins, network_backend or httpcore.AnyIOBackend())
            inner = _PinnedHTTPTransport(verify=verify, network_backend=backend)
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        allow_hosts = loopback_stub_exemption(self._rule.connection)
        try:
            target = await check_connection_target(str(request.url), self._rule, allow_hosts=allow_hosts)
            if self._target_rule is not None:
                self._target_rule(target)
        except OutboundURLPolicyError as refused:
            raise EgressRefusedError(refused.reason, request=request) from None
        self._pins[_pin_key(request.url)] = target.addresses
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def egress_transport(
    connection: str,
    *,
    verify: Any = True,
    inner: httpx.AsyncBaseTransport | None = None,
) -> PinnedEgressTransport:
    """The transport every credentialed client passes as ``httpx.AsyncClient(transport=...)``."""
    return PinnedEgressTransport(connection, verify=verify, inner=inner)


__all__ = ["EgressRefusedError", "PinnedEgressTransport", "REASON_UNPINNED_TARGET", "egress_transport"]
