"""The platform's outbound URL policy: where a server-side HTTP call may go.

Every target is checked after DNS resolution, and again on every redirect hop, so a
hostname that resolves to (or redirects to) a refused address is refused too. Two
explicit scopes exist:

* ``public_only`` (the default): refuses loopback, link-local (cloud metadata),
  unspecified, private (RFC 1918, RFC 6598 shared space, IPv6 ULA) and the named
  metadata hosts. Web fetches, Source Sync and the Atlassian and SCM tools use it.
* ``no_pod_local``: refuses only what can never be a legitimate integration target,
  i.e. the pod's own loopback services (the object store, LiteLLM, the credentials sidecar),
  link-local and cloud metadata addresses (including AWS ``fd00:ec2::/32``) and the
  unspecified address. Connectors whose systems normally live inside the private
  network (Vault, Argo CD, Kubernetes, a self-hosted registry) use it.

IPv4 addresses embedded in IPv6 (mapped ``::ffff:a.b.c.d``, 6to4, NAT64) are checked as
the IPv4 address they reach. A host that does not resolve is refused. Two exact
``host:port`` widenings exist, each owned by a caller that governs it:

* ``allow_hosts``: local Confluence/Jira/SCM stubs (settings-gated, literal loopback
  ``host:port`` only, ``app/loopback_stub_policy.py``);
* ``private_hosts``: the admin-governed on-prem allowlist of a connection
  (``services/outbound_egress/private_hosts.py``). A listed target may reach the private
  network, never the pod-local or metadata ranges.

:func:`check_outbound_target` returns the checked addresses, so a caller can connect to
exactly those (``services/outbound_egress/pinned_transport.py``) instead of resolving again.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

EGRESS_SCOPE_PUBLIC_ONLY = "public_only"
EGRESS_SCOPE_NO_POD_LOCAL = "no_pod_local"
_SCOPES = frozenset({EGRESS_SCOPE_PUBLIC_ONLY, EGRESS_SCOPE_NO_POD_LOCAL})

_ALLOWED_SCHEMES = {"http", "https"}
_DEFAULT_PORTS = {"http": 80, "https": 443}
_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "instance-data.ec2.internal",
}
_BLOCKED_HOSTNAME_SUFFIXES = (".localhost",)
_POD_LOCAL_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fd00:ec2::/32"),
)
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
_NAT64_NETWORK = ipaddress.ip_network("64:ff9b::/96")

# Fixed refusal reasons; callers that must not echo a host report these instead.
REASON_SCHEME_NOT_ALLOWED = "scheme_not_allowed"
REASON_HOST_REQUIRED = "host_required"
REASON_BLOCKED_HOST = "blocked_host"
REASON_BLOCKED_ADDRESS = "blocked_address"
REASON_PRIVATE_ADDRESS_NOT_ALLOWLISTED = "private_address_not_allowlisted"
REASON_UNRESOLVABLE_HOST = "unresolvable_host"


class OutboundURLPolicyError(ValueError):
    """Raised when an outbound target violates the policy; ``reason`` is a fixed code."""

    def __init__(self, message: str, *, reason: str = REASON_BLOCKED_ADDRESS) -> None:
        super().__init__(message)
        self.reason = reason


def _normalized_target(url: str) -> tuple[str, int]:
    parsed = urlsplit(str(url or "").strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise OutboundURLPolicyError("Only http:// and https:// URLs are allowed", reason=REASON_SCHEME_NOT_ALLOWED)
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise OutboundURLPolicyError("URL hostname is required", reason=REASON_HOST_REQUIRED)
    try:
        port = parsed.port or _DEFAULT_PORTS[scheme]
    except ValueError:
        raise OutboundURLPolicyError("URL port is invalid", reason=REASON_HOST_REQUIRED) from None
    return hostname, port


def _is_blocked_hostname(hostname: str) -> bool:
    return hostname in _BLOCKED_HOSTNAMES or any(hostname.endswith(suffix) for suffix in _BLOCKED_HOSTNAME_SUFFIXES)


def _reached_addresses(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> list[ipaddress._BaseAddress]:
    """The address itself plus the IPv4 address an IPv6 transition form actually reaches."""
    addresses: list[ipaddress._BaseAddress] = [ip]
    if ip.version == 6:
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is None and ip in _NAT64_NETWORK:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None:
            addresses.append(embedded)
    return addresses


ADDRESS_CLASS_POD_LOCAL = "pod_local"
ADDRESS_CLASS_PRIVATE = "private"
ADDRESS_CLASS_PUBLIC = "public"


def classify_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """``pod_local`` (never a target), ``private`` (the private network) or ``public``."""

    def _in(networks: tuple) -> bool:
        return any(
            address.version == network.version and address in network
            for address in _reached_addresses(ip)
            for network in networks
        )

    if _in(_POD_LOCAL_NETWORKS):
        return ADDRESS_CLASS_POD_LOCAL
    if _in(_PRIVATE_NETWORKS):
        return ADDRESS_CLASS_PRIVATE
    return ADDRESS_CLASS_PUBLIC


def is_blocked_hostname(hostname: str) -> bool:
    """A name that always means the pod itself or a metadata service."""
    return _is_blocked_hostname(str(hostname or "").strip().lower().rstrip("."))


def _refusal_for(ip: ipaddress._BaseAddress, scope: str, private_admitted: bool) -> str | None:
    address_class = classify_address(ip)
    if address_class == ADDRESS_CLASS_POD_LOCAL:
        return REASON_BLOCKED_ADDRESS
    if address_class == ADDRESS_CLASS_PRIVATE and scope == EGRESS_SCOPE_PUBLIC_ONLY and not private_admitted:
        return REASON_PRIVATE_ADDRESS_NOT_ALLOWLISTED
    return None


async def _resolve_hostname_ips(hostname: str, port: int | None) -> set[ipaddress._BaseAddress]:
    def _lookup() -> set[ipaddress._BaseAddress]:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        addresses: set[ipaddress._BaseAddress] = set()
        for family, _socktype, _proto, _canonname, sockaddr in infos:
            if family == socket.AF_INET:
                addresses.add(ipaddress.ip_address(sockaddr[0]))
            elif family == socket.AF_INET6:
                addresses.add(ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0]))
        return addresses

    return await asyncio.to_thread(_lookup)


@dataclass(frozen=True)
class CheckedTarget:
    """A target the policy admitted, with every address it was checked against."""

    hostname: str
    port: int
    addresses: tuple[str, ...]

    @property
    def host_port(self) -> str:
        return f"{self.hostname}:{self.port}"


async def check_outbound_target(
    url: str,
    *,
    scope: str = EGRESS_SCOPE_PUBLIC_ONLY,
    allow_hosts: frozenset[str] = frozenset(),
    private_hosts: frozenset[str] = frozenset(),
) -> CheckedTarget:
    """Resolve ``url`` once and return the admitted addresses, else raise :class:`OutboundURLPolicyError`.

    Every resolved address must pass; one refused address refuses the target, so a caller that
    connects to any of the returned addresses reaches only checked ones.
    """
    if scope not in _SCOPES:
        raise OutboundURLPolicyError("Unknown outbound URL policy scope", reason=REASON_BLOCKED_HOST)
    hostname, port = _normalized_target(url)
    host_port = f"{hostname}:{port}"
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if host_port in allow_hosts:
        if literal_ip is not None:
            return CheckedTarget(hostname, port, (str(literal_ip),))
        resolved = await _resolved_or_refused(hostname, port)
        return CheckedTarget(hostname, port, tuple(sorted(str(ip) for ip in resolved)))
    if _is_blocked_hostname(hostname):
        raise OutboundURLPolicyError(f"Blocked outbound host: {hostname}", reason=REASON_BLOCKED_HOST)
    addresses = {literal_ip} if literal_ip is not None else await _resolved_or_refused(hostname, port)
    private_admitted = host_port in private_hosts
    for ip in sorted(addresses, key=str):
        reason = _refusal_for(ip, scope, private_admitted)
        if reason is not None:
            raise OutboundURLPolicyError(f"Blocked outbound address: {ip}", reason=reason)
    return CheckedTarget(hostname, port, tuple(sorted(str(ip) for ip in addresses)))


async def _resolved_or_refused(hostname: str, port: int) -> set[ipaddress._BaseAddress]:
    try:
        resolved_ips = await _resolve_hostname_ips(hostname, port)
    except (OSError, UnicodeError):
        resolved_ips = set()
    if not resolved_ips:
        raise OutboundURLPolicyError(
            f"Outbound host could not be resolved: {hostname}", reason=REASON_UNRESOLVABLE_HOST
        ) from None
    return resolved_ips


async def validate_outbound_url(
    url: str,
    *,
    scope: str = EGRESS_SCOPE_PUBLIC_ONLY,
    allow_hosts: frozenset[str] = frozenset(),
    private_hosts: frozenset[str] = frozenset(),
) -> str:
    """Return ``url`` when the policy admits it, else raise :class:`OutboundURLPolicyError`."""
    await check_outbound_target(url, scope=scope, allow_hosts=allow_hosts, private_hosts=private_hosts)
    return url


