"""Shared, pure validation rules for configured Knowledge HTTP endpoints.

The scheme, host, and port rules of the S3-compatible object-store endpoint
(``objects/config.py``), kept pure and apart from the client that uses them.

Rules (fail closed):

- the scheme is exactly ``http`` or ``https``, lower case;
- plain ``http`` is accepted only for an explicit loopback host (``localhost``,
  ``127.0.0.0/8``, ``[::1]``); every other host requires ``https``;
- userinfo, query strings (even empty), fragments, backslashes, and any path
  other than ``/`` are rejected, so no credential or routing hint can hide in a
  configured URL;
- hosts are lower-case DNS names or IP literals; unspecified addresses, IPv6
  zone identifiers, IPv4-mapped IPv6 addresses, and numeric-looking host names
  (``127.1``) are rejected.

This module is pure: it raises nothing and knows no error taxonomy. Each
boundary maps a ``None`` result onto its own typed configuration error, so a
rejection never carries the offending value.
"""

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
    """True for a lower-case DNS name or a usable IP literal."""
    if type(host) is not str or not host or len(host) > 253 or "%" in host:
        return False
    ip = _parse_ip(host)
    if ip is not None:
        return not ip.is_unspecified and not (ip.version == 6 and ip.ipv4_mapped is not None)
    labels = host.split(".")
    # A numeric last label is how resolvers accept legacy IPv4 forms ("127.1").
    return all(_HOST_LABEL.fullmatch(label) for label in labels) and not labels[-1].isdigit()


def is_loopback_host(host: object) -> bool:
    """True only for ``localhost``, an IPv4 loopback address, or ``::1``."""
    if type(host) is not str:
        return False
    if host in _LOOPBACK_NAMES:
        return True
    ip = _parse_ip(host)
    if ip is None:
        return False
    return (ip.version == 4 and ip.is_loopback) or ip == _IPV6_LOOPBACK


def is_valid_port(port: object) -> bool:
    return type(port) is int and 1 <= port <= 65535


def is_allowed_scheme_for_host(scheme: object, host: object) -> bool:
    """True when the scheme is known and plaintext is confined to loopback."""
    if type(scheme) is not str or scheme not in SCHEME_DEFAULT_PORTS:
        return False
    return scheme != "http" or is_loopback_host(host)


def split_endpoint(raw: object) -> tuple[str, str, int] | None:
    """Split a configured endpoint URL into ``(scheme, host, port)``.

    Returns ``None`` for every rejected input, including a non-string, so the
    caller raises its own fixed error without echoing the value. An absent or
    empty endpoint is the caller's "not configured" case and must be handled
    before calling this function.
    """
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
    """Canonical origin form; IPv6 literals stay bracketed."""
    rendered_host = f"[{host}]" if ":" in host else host
    return f"{scheme}://{rendered_host}:{port}"
