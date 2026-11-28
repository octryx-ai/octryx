"""The platform's outbound URL policy: where a server-side HTTP call may go."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from .outbound_url_types import AddressClass, EgressScope

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
    # IPv6 transition forms are checked by the IPv4 address they actually reach.
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


def classify_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> AddressClass:
    # ``pod_local`` is never a target.

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
    return _is_blocked_hostname(str(hostname or "").strip().lower().rstrip("."))


def _refusal_for(ip: ipaddress._BaseAddress, scope: EgressScope, private_admitted: bool) -> str | None:
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
    # Transports must connect to the returned addresses: a second DNS lookup could substitute unchecked ones. Outside
    # ``allow_hosts``, every address passes the filter, and one refused address refuses the whole target.
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
    scope: EgressScope = EGRESS_SCOPE_PUBLIC_ONLY,
    allow_hosts: frozenset[str] = frozenset(),
    private_hosts: frozenset[str] = frozenset(),
) -> str:
    await check_outbound_target(url, scope=scope, allow_hosts=allow_hosts, private_hosts=private_hosts)
    return url


