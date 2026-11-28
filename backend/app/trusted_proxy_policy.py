"""Validated trusted-proxy boundary for request scheme and client identity."""

from __future__ import annotations

import ipaddress
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from starlette.datastructures import Headers

from .config import (
    Settings,
    forwarded_header_trust_mode,
    get_settings,
    is_production_like_runtime_profile,
    trusted_proxy_networks,
)

logger = logging.getLogger(__name__)

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Headers a reverse proxy may use to describe the original request. Any of them
# is evidence that the request did not arrive directly from the peer we see.
FORWARDED_REQUEST_HEADERS = (
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-host",
    "x-forwarded-port",
)

FORWARDED_SCHEMES = frozenset({"http", "https", "ws", "wss"})
SECURE_SCHEMES = frozenset({"https", "wss"})

CLIENT_SOURCE_TRANSPORT_PEER = "transport_peer"
CLIENT_SOURCE_TRUSTED_PROXY = "trusted_proxy_forwarded"

# Key under which the resolved identity is recorded in the ASGI scope state.
SCOPE_STATE_KEY = "trusted_proxy_client_identity"

UNKNOWN_CLIENT_ADDRESS = "unknown"

# A forwarded header can list arbitrarily many hops; only this many are read, and
# an address literal is never longer than an IPv6 address with a zone suffix.
#
# Which end of an over-long chain survives truncation is a security decision, not
# a detail: each proxy *appends* the peer it received the request from, so the
# trustworthy evidence is at the right. Keeping the leftmost elements would let a
# client pad the header past the bound, drop the entry its proxy appended, and so
# choose the address the rightmost-wins scan selects. Client selection therefore
# keeps the rightmost elements (``_KEEP_TRAILING``).
#
# The scheme claim keeps *both* ends (``_KEEP_BOTH_ENDS``): the leftmost element
# is the documented first-hop reading, and the rightmost elements carry the claim
# the trusted proxy appended, which fail-secure resolution must not lose. Only
# middle elements of an over-long chain are dropped; they are neither the first
# hop nor the proxy's own claim, and a secure claim there could not be trusted
# more than the proxy's.
MAX_FORWARDED_ELEMENTS = 32
MAX_ADDRESS_LENGTH = 45

_KEEP_TRAILING = "trailing"
_KEEP_BOTH_ENDS = "both_ends"


@dataclass(frozen=True)
class ClientIdentity:
    peer_address: str
    client_address: str
    scheme: str
    via_trusted_proxy: bool
    forwarded_headers_present: bool
    source: str = CLIENT_SOURCE_TRANSPORT_PEER
    # True when ``scheme`` was raised by a trusted proxy's claim instead of the
    # transport itself; auth-cookie auditing distinguishes the two cases.
    forwarded_scheme_applied: bool = False

    @property
    def is_forwarded(self) -> bool:
        return self.source == CLIENT_SOURCE_TRUSTED_PROXY


def parse_ip_address(value: str | None) -> IpAddress | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("["):
        raw = raw[1:].partition("]")[0]
    elif raw.count(":") == 1:
        raw = raw.partition(":")[0]
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return None
    return getattr(address, "ipv4_mapped", None) or address


def is_trusted_proxy_peer(peer_address: str | None, settings: Settings) -> bool:
    networks = trusted_proxy_networks(str(settings.trusted_proxy_ips or ""))
    if not networks:
        return False
    address = parse_ip_address(peer_address)
    if address is None:
        return False
    return any(address in network for network in networks)


def _has_forwarded_headers(headers: Mapping[str, str] | Headers | None) -> bool:
    if headers is None:
        return False
    return any(header in headers for header in FORWARDED_REQUEST_HEADERS)


def _header_occurrences(headers: Mapping[str, str] | Headers | None, name: str) -> list[str]:
    if headers is None:
        return []
    getlist = getattr(headers, "getlist", None)
    if callable(getlist):
        return [str(value) for value in getlist(name)]
    if isinstance(headers, Mapping):
        value = headers.get(name)
        return [] if value is None else [str(value)]
    raise TypeError("forwarded headers must be a starlette Headers or a Mapping")


def _comma_entries(headers: Mapping[str, str] | Headers | None, name: str) -> list[str]:
    entries: list[str] = []
    for occurrence in _header_occurrences(headers, name):
        for candidate in occurrence.split(","):
            item = candidate.strip()
            if item:
                entries.append(item)
    return entries


def _bounded(elements: list[str], keep: str) -> list[str]:
    if len(elements) <= MAX_FORWARDED_ELEMENTS:
        return elements
    if keep == _KEEP_TRAILING:
        return elements[-MAX_FORWARDED_ELEMENTS:]
    half = MAX_FORWARDED_ELEMENTS // 2
    return elements[:half] + elements[-half:]


def _forwarded_elements(
    headers: Mapping[str, str] | Headers | None,
    *,
    keep: str = _KEEP_TRAILING,
) -> list[dict[str, str]]:
    elements: list[dict[str, str]] = []
    for element in _bounded(_comma_entries(headers, "forwarded"), keep):
        parameters: dict[str, str] = {}
        for part in element.split(";"):
            key, separator, value = part.partition("=")
            if not separator:
                continue
            parameters[key.strip().lower()] = value.strip().strip('"')
        if parameters:
            elements.append(parameters)
    return elements


def forwarded_scheme(headers: Mapping[str, str] | Headers | None) -> str:
    claimed = [entry.lower() for entry in _bounded(_comma_entries(headers, "x-forwarded-proto"), _KEEP_BOTH_ENDS)]
    claimed += [element.get("proto", "").lower() for element in _forwarded_elements(headers, keep=_KEEP_BOTH_ENDS)]
    valid = [candidate for candidate in claimed if candidate in FORWARDED_SCHEMES]
    if not valid:
        return ""
    for candidate in valid:
        if candidate in SECURE_SCHEMES:
            return candidate
    return valid[0]


def _effective_scheme(transport_scheme: str, claimed_scheme: str) -> str:
    transport = str(transport_scheme or "").strip().lower()
    if transport in SECURE_SCHEMES or not claimed_scheme:
        return transport
    websocket_transport = transport in {"ws", "wss"}
    claimed_secure = claimed_scheme in SECURE_SCHEMES
    if websocket_transport:
        return "wss" if claimed_secure else "ws"
    return "https" if claimed_secure else "http"


def _forwarded_client_address(
    headers: Mapping[str, str] | Headers | None,
    settings: Settings,
) -> str:
    entries = _bounded(_comma_entries(headers, "x-forwarded-for"), _KEEP_TRAILING)
    if not entries:
        # RFC 7239 proxies that only emit ``Forwarded: for=`` are read the same way.
        entries = [
            element["for"]
            for element in _forwarded_elements(headers, keep=_KEEP_TRAILING)
            if element.get("for")
        ]
    if not entries:
        return ""
    for entry in reversed(entries):
        address = parse_ip_address(entry)
        if address is not None and not is_trusted_proxy_peer(str(address), settings):
            return str(address)
    leftmost = parse_ip_address(entries[0])
    return str(leftmost) if leftmost is not None else ""


def resolve_client_identity(
    *,
    peer_address: str | None,
    transport_scheme: str,
    headers: Mapping[str, str] | Headers | None,
    settings: Settings,
) -> ClientIdentity:
    peer = parse_ip_address(peer_address)
    peer_text = str(peer) if peer is not None else str(peer_address or "").strip()[:MAX_ADDRESS_LENGTH]
    forwarded_present = _has_forwarded_headers(headers)
    trusted = is_trusted_proxy_peer(peer_text, settings)

    if not trusted:
        return ClientIdentity(
            peer_address=peer_text,
            client_address=peer_text,
            scheme=str(transport_scheme or "").strip().lower(),
            via_trusted_proxy=False,
            forwarded_headers_present=forwarded_present,
            source=CLIENT_SOURCE_TRANSPORT_PEER,
        )

    forwarded_client = _forwarded_client_address(headers, settings)
    transport = str(transport_scheme or "").strip().lower()
    scheme = _effective_scheme(transport, forwarded_scheme(headers))
    return ClientIdentity(
        peer_address=peer_text,
        client_address=forwarded_client or peer_text,
        scheme=scheme,
        via_trusted_proxy=True,
        forwarded_headers_present=forwarded_present,
        source=CLIENT_SOURCE_TRUSTED_PROXY if forwarded_client else CLIENT_SOURCE_TRANSPORT_PEER,
        forwarded_scheme_applied=scheme != transport,
    )


def resolve_scope_client_identity(scope: Any, settings: Settings) -> ClientIdentity:
    client = scope.get("client") if hasattr(scope, "get") else None
    peer_address = client[0] if client else None
    return resolve_client_identity(
        peer_address=peer_address,
        transport_scheme=str(scope.get("scheme") or ""),
        headers=Headers(scope=scope),
        settings=settings,
    )


def record_client_identity(scope: Any, identity: ClientIdentity) -> None:
    scope[SCOPE_STATE_KEY] = identity
    scope.setdefault("state", {})[SCOPE_STATE_KEY] = identity


def recorded_client_identity(request: Any) -> ClientIdentity | None:
    scope = getattr(request, "scope", None)
    if not isinstance(scope, dict):
        return None
    identity = scope.get(SCOPE_STATE_KEY)
    if not isinstance(identity, ClientIdentity):
        state = scope.get("state")
        identity = state.get(SCOPE_STATE_KEY) if isinstance(state, dict) else None
    return identity if isinstance(identity, ClientIdentity) else None


def client_identity(request: Any, settings: Settings | None = None) -> ClientIdentity:
    recorded = recorded_client_identity(request)
    if recorded is not None:
        return recorded
    resolved = settings or get_settings()
    client = getattr(request, "client", None)
    url = getattr(request, "url", None)
    return resolve_client_identity(
        peer_address=getattr(client, "host", None),
        transport_scheme=str(getattr(url, "scheme", "") or ""),
        headers=getattr(request, "headers", None),
        settings=resolved,
    )


def effective_client_address(request: Any, settings: Settings | None = None) -> str | None:
    if request is None:
        return None
    return client_identity(request, settings).client_address or None


def rate_limit_client_key(request: Any, settings: Settings | None = None) -> str:
    return effective_client_address(request, settings) or UNKNOWN_CLIENT_ADDRESS


def log_boundary_configuration(settings: Settings | None = None) -> str:
    resolved = settings or get_settings()
    mode = forwarded_header_trust_mode(resolved.trusted_proxy_ips)
    logger.info("Trusted-proxy boundary active (forwarded_header_trust=%s)", mode)
    if mode == "disabled" and is_production_like_runtime_profile(resolved.runtime_profile):
        logger.warning(
            "TRUSTED_PROXY_IPS is empty for a production-like runtime: forwarded headers are ignored, "
            "so client address, rate-limit bucketing, audit attribution, and absolute URLs use the "
            "transport peer. Set it to the ingress/proxy addresses when running behind a reverse proxy."
        )
    if os.environ.get("FORWARDED_ALLOW_IPS"):
        logger.warning(
            "FORWARDED_ALLOW_IPS is set in the environment but the transport layer does not evaluate "
            "forwarded headers; use TRUSTED_PROXY_IPS instead."
        )
    return mode


def uvicorn_forwarded_header_options() -> dict[str, object]:
    return {"proxy_headers": False, "forwarded_allow_ips": []}


__all__ = [
    "CLIENT_SOURCE_TRANSPORT_PEER",
    "CLIENT_SOURCE_TRUSTED_PROXY",
    "FORWARDED_REQUEST_HEADERS",
    "SCOPE_STATE_KEY",
    "UNKNOWN_CLIENT_ADDRESS",
    "ClientIdentity",
    "client_identity",
    "effective_client_address",
    "forwarded_scheme",
    "is_trusted_proxy_peer",
    "log_boundary_configuration",
    "parse_ip_address",
    "rate_limit_client_key",
    "record_client_identity",
    "recorded_client_identity",
    "resolve_client_identity",
    "resolve_scope_client_identity",
    "uvicorn_forwarded_header_options",
]
