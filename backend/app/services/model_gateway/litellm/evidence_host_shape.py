"""Host-shaped admission for the closed gateway evidence fields (Issue).

The evidence writer refuses any string the shared redaction policy considers
secret-shaped. That policy matches a credential prefix such as ``sk-`` as a
*substring*, on purpose: an API key pasted into the middle of a free-text field
must still be caught. Gateway evidence, however, records the deployment's own
hostnames in closed fields, and a perfectly ordinary internal hostname can
contain such a substring — ``litellm.nonprod.example.com`` carries
``sk-`` inside the label ``nonprod``. The writer refused it, so the
qualification could not produce evidence for the very environment it gates.

Weakening the generic policy is the wrong fix: it protects every other payload
in the repository. Instead, the three closed fields that are *defined* to hold a
host admit a value only when it is provably a host:

- the value matches a strict RFC-1123 hostname or an IP literal, so its entire
  character set is ``[a-z0-9.-]`` (or hex and ``:`` for IPv6). No space, no
  ``://``, no ``@``, no ``=``, no ``_`` can occur — which is what makes every
  remaining rule in ``redaction_policy`` structurally unable to match: a
  credential URL, an ``Authorization`` header, a ``key=value`` assignment and a
  PEM block all need one of those characters;
- **and** no DNS label *begins* with a known credential prefix. A real token is
  a prefix (``sk-``, ``ghp_``, ``xoxb-``), so ``sk-live-4eC39H.example.com``
  stays refused while ``nonprod`` is admitted.

Anything that fails either rule falls through to the generic secret scan, so a
key, a token or a credential-bearing URL in a host field still fails closed.
"""

from __future__ import annotations

import ipaddress
import re

from ...redaction_policy import SENSITIVE_VALUE_PREFIXES

# Closed evidence keys whose value is a bare host (``evidence.py``).
HOST_EVIDENCE_KEYS = frozenset({"endpoint_host", "proxy_host"})
# Closed evidence keys whose value is a rendered network hop rule
# (``network_path.py``: ``<role>:<scheme>:<host>:<port>``).
HOP_RULE_EVIDENCE_KEYS = frozenset({"network_path_hops"})

MAX_HOST_LENGTH = 253
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# Derived from the shared policy rather than restated, so a prefix added there
# tightens this check too. Only the prefixes that a DNS label could actually
# begin with are kept: ``bearer ``/``basic `` carry a space and ``gho_``/``ghp_``
# /``github_pat_`` carry an underscore, so no valid label can start with them,
# and excluding them keeps an ordinary host like ``basic-gw.example.com`` out of
# a false refusal.
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
    """True when ``value`` is provably a hostname or IP literal, not a secret."""

    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_HOST_LENGTH:
        return False
    if candidate != candidate.lower():
        # Evidence hosts are normalized to lower case at validation time, so a
        # mixed-case value did not come from the endpoint or proxy validator.
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
    """True when ``value`` is a rendered ``<role>:<scheme>:<host>:<port>`` rule.

    Each of the four parts is checked against its own closed set, so the whole
    string is admissible by construction rather than by pattern matching. The
    host is split off from the right, because an IPv6 literal contains colons.
    """

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
    """True when ``value`` is the host-shaped content its closed key promises."""

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
