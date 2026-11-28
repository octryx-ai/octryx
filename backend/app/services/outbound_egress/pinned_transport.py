"""A pinned ``httpx`` transport: a credentialed request connects only to the address the policy checked."""

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
    """Checks every request with the connection's egress rule and connects only to checked addresses."""

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
