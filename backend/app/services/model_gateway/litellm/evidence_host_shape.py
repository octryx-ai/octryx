"""Host-shaped admission for the closed gateway evidence fields (Issue)."""

from __future__ import annotations

import ipaddress
import re

from ...redaction_policy import SENSITIVE_VALUE_PREFIXES

# Closed evidence keys whose value is a bare host (``evidence.py``).
HOST_EVIDENCE_KEYS = frozenset({"endpoint_host", "proxy_host"})
# Closed evidence keys whose value is a hop rule (``network_path.py``: ``<role>:<scheme>:<host>:<port>``).
HOP_RULE_EVIDENCE_KEYS = frozenset({"network_path_hops"})

MAX_HOST_LENGTH = 253
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# Derived from the shared policy so a new prefix tightens this too; only prefixes a DNS label can begin with are
# kept, so an ordinary host like ``basic-gw.example.com`` is not falsely refused.
_LABEL_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
_CREDENTIAL_LABEL_PREFIXES = tuple(
    prefix for prefix in SENSITIVE_VALUE_PREFIXES if prefix and set(prefix) <= _LABEL_CHARACTERS
)

_HOP_ROLES = frozenset({"direct_egress", "proxy_egress", "tunneled_destination"})
_HOP_SCHEMES = frozenset({"http", "https"})
_MIN_PORT = 1
_MAX_PORT = 65535


def _is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def is_host_shaped(value: object) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_HOST_LENGTH:
        return False
    if candidate != candidate.lower():
        # Hosts are lower-cased at validation, so a mixed-case value did not come from the endpoint or proxy validator.
        return False
    if _is_ip_literal(candidate):
        return True
    labels = candidate.split(".")
    if not all(_LABEL_RE.match(label) for label in labels):
        return False
    # A credential prefix is a prefix. Inside a label it is ordinary text
    # (``nonprod``); at the start of one it is the shape of a real token.
    return not any(label.startswith(prefix) for label in labels for prefix in _CREDENTIAL_LABEL_PREFIXES)


def is_hop_rule_shaped(value: object) -> bool:
    if not isinstance(value, str):
        return False
    head, separator, port_text = value.rpartition(":")
    if not separator or not port_text.isdigit():
        return False
    port = int(port_text)
    if port < _MIN_PORT or port > _MAX_PORT:
        return False
    parts = head.split(":", 2)
    if len(parts) != 3:
        return False
    role, scheme, host = parts
    return role in _HOP_ROLES and scheme in _HOP_SCHEMES and is_host_shaped(host)


def is_admissible_host_evidence(key: str, value: object) -> bool:
    if key in HOST_EVIDENCE_KEYS:
        return is_host_shaped(value)
    if key in HOP_RULE_EVIDENCE_KEYS:
        return is_hop_rule_shaped(value)
    return False


__all__ = [
    "HOP_RULE_EVIDENCE_KEYS",
    "HOST_EVIDENCE_KEYS",
    "MAX_HOST_LENGTH",
    "is_admissible_host_evidence",
    "is_host_shaped",
    "is_hop_rule_shaped",
]
