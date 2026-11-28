"""Shared, pure validation rules for configured Knowledge HTTP endpoints (fail closed). Plain ``http`` only on loopback
or a single-label service name; userinfo, query, fragment and paths are rejected."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

MAX_ENDPOINT_CHARS = 512
SCHEME_DEFAULT_PORTS = {"http": 80, "https": 443}

_PRINTABLE_ASCII = re.compile(r"^[\x21-\x7e]+$")
_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
# Lower-case host or bracketed IPv6 literal, optional port without leading zero.
_NETLOC = re.compile(r"^(?:[a-z0-9.-]+|\[[0-9a-f:.]+\])(?::[1-9][0-9]{0,4})?$")
_LOOPBACK_NAMES = frozenset({"localhost"})
_IPV6_LOOPBACK = ipaddress.IPv6Address("::1")
_REJECTED_MARKERS = ("@", "?", "#", "\\")


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def is_valid_host(host: object) -> bool:
    if type(host) is not str or not host or len(host) > 253 or "%" in host:
        return False
    ip = _parse_ip(host)
    if ip is not None:
        return not ip.is_unspecified and not (ip.version == 6 and ip.ipv4_mapped is not None)
    labels = host.split(".")
    # A numeric last label is how resolvers accept legacy IPv4 forms ("127.1").
    return all(_HOST_LABEL.fullmatch(label) for label in labels) and not labels[-1].isdigit()


def is_loopback_host(host: object) -> bool:
    if type(host) is not str:
        return False
    if host in _LOOPBACK_NAMES:
        return True
    ip = _parse_ip(host)
    if ip is None:
        return False
    return (ip.version == 4 and ip.is_loopback) or ip == _IPV6_LOOPBACK


def _is_service_name(host: object) -> bool:
    # A dotless name only resolves on the deployment's own network (a compose or cluster service), never publicly.
    return type(host) is str and "." not in host and _parse_ip(host) is None


def is_valid_port(port: object) -> bool:
    return type(port) is int and 1 <= port <= 65535


def is_allowed_scheme_for_host(scheme: object, host: object) -> bool:
    if type(scheme) is not str or scheme not in SCHEME_DEFAULT_PORTS:
        return False
    return scheme != "http" or is_loopback_host(host) or _is_service_name(host)


def split_endpoint(raw: object) -> tuple[str, str, int] | None:
    # None for every rejected input, so the caller raises its own error without echoing the value.
    if type(raw) is not str or not raw or len(raw) > MAX_ENDPOINT_CHARS:
        return None
    if not _PRINTABLE_ASCII.fullmatch(raw):
        return None
    # Rejected before parsing: urlsplit silently drops empty queries and fragments.
    if any(marker in raw for marker in _REJECTED_MARKERS):
        return None
    parts = urlsplit(raw)
    scheme = parts.scheme
    if scheme not in SCHEME_DEFAULT_PORTS or not raw.startswith(f"{scheme}://"):
        return None
    if parts.path not in ("", "/") or not _NETLOC.fullmatch(parts.netloc):
        return None
    host = parts.hostname
    if host is None or not is_valid_host(host):
        return None
    try:
        port = parts.port
    except ValueError:  # out of range for an int port
        return None
    if port is None:
        port = SCHEME_DEFAULT_PORTS[scheme]
    if not is_valid_port(port) or not is_allowed_scheme_for_host(scheme, host):
        return None
    return scheme, host, port


def base_url(scheme: str, host: str, port: int) -> str:
    rendered_host = f"[{host}]" if ":" in host else host
    return f"{scheme}://{rendered_host}:{port}"
