"""Validated trusted-proxy boundary for request scheme and client identity.

One module decides, from one validated configuration (``trusted_proxy_ips``),
what a request's effective scheme and effective client address are. Every
security surface that depends on those two values — the auth-cookie policy
the API and auth rate limiters, and request/auth audit attribution —
reads the decision from here instead of parsing forwarded headers itself.

Resolution rules, in order:

1. The transport peer is not in the allowlist -> forwarded headers are ignored
   completely: the client is the peer, the scheme is the transport scheme.
2. The peer is in the allowlist -> ``X-Forwarded-For`` may name the client and
   ``X-Forwarded-Proto`` / ``Forwarded: proto=`` may name the scheme.
3. A trusted peer without a usable forwarded address stays attributed to the
   peer (the proxy) rather than to an unparseable claim.

Invariants that hold in every case:

- A secure transport (``https``/``wss``) is never downgraded by a header.
- A secure claim anywhere in the forwarded scheme evidence wins, so a
  client-supplied ``http`` cannot suppress the ``https`` its proxy claimed.
- Only syntactically valid IP addresses become a client address, so header text
  can never reach rate-limit keys or audit rows.
- The allowlist is deny-by-default and cannot express trust-all (see
  ``config.parse_trusted_proxy_ips``).
- Every occurrence of a forwarded header is read, in wire order, before any
  bounding or selection happens (see ``_header_occurrences``).
- The original transport peer and the trust decision remain available after the
  effective client has been applied to the scope, so peer-based policies (the
  local-debug cookie exemption) keep evaluating the real peer.

Boundaries of this contract, deliberately chosen:

- Every address in the allowlist may speak for any client. Name the proxy
  addresses as narrowly as possible: a client inside a broad allowlisted network
  can forge its own attribution.
- Scheme resolution is fail-secure rather than positional: all
  ``X-Forwarded-Proto`` values and all ``Forwarded: proto=`` values are combined,
  and a secure claim among them wins over any insecure one. A forged ``https``
  claim can only make the runtime stricter — ``Secure`` cookies and HTTPS URLs —
  and never downgrades: a claimed ``http`` cannot lower a secure transport, and
  any forwarded header already disqualifies the local-debug exemption. When no
  claim is secure, the leftmost insecure claim (the scheme towards the first hop)
  is used, matching the policy.
- A forwarded chain longer than ``MAX_FORWARDED_ELEMENTS`` is truncated; which
  end survives is a security decision, see the constant's comment.
"""

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
    """Effective client attribution for one request.

    ``peer_address`` is always the transport peer, never header-derived.
    ``client_address`` is the address security surfaces should attribute the
    request to. ``source`` records which of the two the client came from.
    """

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
    """Parse a peer/forwarded address, or return ``None`` when it is not one.

    Accepts the shapes proxies actually emit: a bare address, a bracketed IPv6
    literal, and ``address:port`` for IPv4. IPv4-mapped IPv6 is normalized to
    its IPv4 form so allowlists can be written in one family.
    """
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
    """True when the transport peer is named by the trusted-proxy allowlist."""
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
    """Every occurrence of one header field, in wire order.

    A comma-list header may arrive as several field lines, and HTTP defines that
    to mean the same as one comma-joined list in the order received. A client can
    therefore send its own ``X-Forwarded-For`` line and let the proxy append a
    *second* line instead of extending the first. Reading only
    ``headers.get(name)`` would take Starlette's *first* occurrence, i.e. the
    client-supplied one, and hand the whole attribution decision to the client.

    Starlette ``Headers`` expose ``getlist``; a plain ``Mapping`` (used by helpers
    and tests) carries at most one value per name. Anything else is a programming
    error at the call site, not an input to guess about, so it is rejected instead
    of silently read as empty.
    """
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
    """Comma-separated entries of every occurrence of one header, in wire order.

    Combining happens here, before any bound or selection is applied, so the
    rightmost/leftmost decisions below operate on the complete chain rather than
    on whichever field line happened to arrive first.
    """
    entries: list[str] = []
    for occurrence in _header_occurrences(headers, name):
        for candidate in occurrence.split(","):
            item = candidate.strip()
            if item:
                entries.append(item)
    return entries


def _bounded(elements: list[str], keep: str) -> list[str]:
    """At most ``MAX_FORWARDED_ELEMENTS`` elements, kept from the named end(s)."""
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
    """Parameters of each ``Forwarded`` element (RFC 7239), in request order.

    All occurrences of the header are combined first, then bounded to
    ``MAX_FORWARDED_ELEMENTS``; ``keep`` decides which end of an over-long chain
    survives (see the constant's comment for why that matters).
    """
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
    """Scheme claimed by a proxy, or an empty string when none is claimed.

    Fail-secure rather than positional: every occurrence of ``X-Forwarded-Proto``
    and every ``Forwarded`` element is combined, and a secure claim anywhere in
    that evidence wins. A client that prepends ``http`` — as its own header line
    or as the first list element — therefore cannot suppress the ``https`` its
    trusted proxy claimed. With no secure claim at all, the leftmost insecure
    claim is returned (``X-Forwarded-Proto`` before ``Forwarded: proto=``), which
    cannot downgrade a secure transport either (``_effective_scheme``).
    """
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
    """Apply a claimed scheme to the transport scheme without downgrading it."""
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
    """Client address vouched for by a trusted proxy chain, or an empty string.

    Each proxy appends the address it received the request from, so the client
    is the rightmost entry that is not itself a trusted proxy. When every entry
    belongs to the trusted chain the leftmost retained entry is the client.

    All occurrences of the header are combined in wire order first, so a client
    that sends its own ``X-Forwarded-For`` line cannot hide the line its proxy
    added. The combined chain is then truncated to its rightmost
    ``MAX_FORWARDED_ELEMENTS`` entries, so a client cannot pad the header to push
    the entry its proxy appended out of the window either.
    """
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
    """Resolve the effective client identity for one request."""
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
    """Resolve the identity for a raw ASGI connection scope."""
    client = scope.get("client") if hasattr(scope, "get") else None
    peer_address = client[0] if client else None
    return resolve_client_identity(
        peer_address=peer_address,
        transport_scheme=str(scope.get("scheme") or ""),
        headers=Headers(scope=scope),
        settings=settings,
    )


def record_client_identity(scope: Any, identity: ClientIdentity) -> None:
    """Record the resolved identity in the ASGI scope.

    Written to the scope itself and to ``scope["state"]``: the scope key keeps the
    decision (and with it the original transport peer) readable even if a
    sub-application replaces the request state, which would otherwise make the
    fallback re-resolve trust from an already-rewritten client address.
    """
    scope[SCOPE_STATE_KEY] = identity
    scope.setdefault("state", {})[SCOPE_STATE_KEY] = identity


def recorded_client_identity(request: Any) -> ClientIdentity | None:
    """The identity recorded by the boundary middleware, if it ran."""
    scope = getattr(request, "scope", None)
    if not isinstance(scope, dict):
        return None
    identity = scope.get(SCOPE_STATE_KEY)
    if not isinstance(identity, ClientIdentity):
        state = scope.get("state")
        identity = state.get(SCOPE_STATE_KEY) if isinstance(state, dict) else None
    return identity if isinstance(identity, ClientIdentity) else None


def client_identity(request: Any, settings: Settings | None = None) -> ClientIdentity:
    """Effective client identity for a request.

    Prefers the identity recorded by the boundary middleware; falls back to
    resolving it from the request, which keeps helpers usable for requests that
    were built outside the middleware stack.
    """
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
    """Address to attribute a request to, or ``None`` when there is no peer."""
    if request is None:
        return None
    return client_identity(request, settings).client_address or None


def rate_limit_client_key(request: Any, settings: Settings | None = None) -> str:
    """Bucket key component for rate limiting: a validated address only."""
    return effective_client_address(request, settings) or UNKNOWN_CLIENT_ADDRESS


def log_boundary_configuration(settings: Settings | None = None) -> str:
    """Log the proxy trust boundary once at startup and return the mode.

    An empty allowlist is valid (direct exposure), but for a production-like
    runtime it usually means an ingress deployment forgot to name its proxies:
    every request is then attributed to the ingress peer and absolute URLs are
    built from the scheme the application itself sees. That is a configuration
    problem an operator must see, not a reason to refuse startup.
    """
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
    """Uvicorn options for the forwarded-header boundary.

    Uvicorn's own ``ProxyHeadersMiddleware`` stays off: the application applies
    the validated ``trusted_proxy_ips`` allowlist itself in
    ``middleware.security.trusted_proxy``, which keeps one authority for every
    launch path (``python -m app.main``, the uvicorn CLI, the e2e helper) and
    keeps the original transport peer available to peer-based policies. The
    empty allowlist is passed explicitly so an ambient ``FORWARDED_ALLOW_IPS``
    cannot re-enable transport-level trust.
    """
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
