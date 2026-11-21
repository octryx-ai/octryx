"""The built-in detectors behind the platform's shipped content policies (``content_security.handling``).

Same contract as ``builtin`` (its RE2 compiler and candidate limit): RE2 finds candidates in linear time, small
Python checks decide, a text with more candidates than ``builtin.MAX_CANDIDATES`` marks the scan incomplete.

- ``credential_assignment`` (secrets, medium): a literal value assigned to ``password``/``passwd``/``pwd`` (4+
  characters) or ``api_key``/``token``/``secret`` (12+ characters). Only the value is the finding, so a masked
  text keeps ``password=``. A placeholder (``$VAR``, ``${...}``, ``<...>``, ``%s``, ``***``) or a code reference
  (``settings.db_password``, ``os.getenv(...)``) is not a value. A quoted key counts (``"password": "..."``);
  :func:`credential_field` decides a structured field (name ending in one of those names, the whole value). The
  gateway secret scan (detector ``secrets``) leaves these out on purpose; this detector is what the platform
  masks on its own model calls.
- ``internal_ip`` (internal_network, medium): an IPv4 address in 10/8, 172.16/12 or 192.168/16, octets <= 255.
- ``prompt_injection`` (prompt_injection, medium): instruction-override phrases (ignore/disregard/forget ...
  previous/earlier/all ... instructions/prompt; do anything now, DAN mode, jailbreak, developer mode; you are now;
  act as (not "act as an enterprise/infrastructure ..."); pretend you are / pretend to be).
  :func:`is_role_phrasing` names the one role-phrasing form ("act as ..."); "you are now" is never role phrasing.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .builtin import _compile, _matches
from .findings import Finding
from .vocabulary import (
    CATEGORY_INTERNAL_NETWORK,
    CATEGORY_PROMPT_INJECTION,
    CATEGORY_SECRETS,
    CONFIDENCE_MEDIUM,
    DETECTOR_CREDENTIAL_ASSIGNMENT,
    DETECTOR_INTERNAL_IP,
    DETECTOR_PROMPT_INJECTION,
)

# The name may close a quoted key (``"password": "..."``, also JSON-escaped ``\\"password\\": \\"...\\"``).
_ASSIGNMENT = _compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\b\\?['\"]?\s*[:=]\s*\\?['\"]?([^\s'\"`,;\\]{4,})"
)
# A structured field (a tool argument, a JSON object) whose name ends in a credential name: ``password``,
# ``db_password``, ``client-secret``, ``access_token``.
_FIELD_NAME = re.compile(r"(?i)^(?:[a-z0-9]+[_-])*(api[_-]?key|token|secret|password|passwd|pwd)$")
_PASSWORD_NAMES = frozenset({"password", "passwd", "pwd"})
_MIN_KEY_LENGTH = 12
_PLACEHOLDER_STARTS = ("$", "{", "<", "%", "*", "[")
_KEY_VALUE = re.compile(r"[A-Za-z0-9_\-]+")
_IPV4 = _compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b"
)
_INJECTION = tuple(_compile(pattern) for pattern in (
    r"(?i)\b(?:ignore|disregard|forget)\b.{0,40}\b(?:previous|earlier|all)\b.{0,40}\b(?:instructions?|prompt)\b",
    r"(?i)\b(?:do anything now|dan mode|jailbreak|developer mode)\b",
    r"(?i)\byou are now\b",
    r"(?i)\bpretend (?:you are|to be)\b",
))
_ACT_AS = _compile(r"(?i)\bact as (?:an? )?(\w+)")
_ACT_AS_EXEMPT = frozenset({"enterprise", "infrastructure"})
# Role phrasing: the owner-approved "Act as ..." form an administrator states an agent's role with. Exempt from the
# refusal only in administrator-authored system text (``content_security.message_trust``); everywhere else it is an
# injection finding like the others.
_ROLE_PHRASING = re.compile(r"(?i)act as (?:an? )?\w+")


# ``settings.db_password``, ``self.token``: a code reference, not a value.
_REFERENCE = re.compile(r"^[a-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _literal_value(name: str, value: str) -> bool:
    if value.startswith(_PLACEHOLDER_STARTS) or "(" in value or _REFERENCE.match(value):
        return False
    if name.lower() in _PASSWORD_NAMES:
        return True
    return len(value) >= _MIN_KEY_LENGTH and _KEY_VALUE.fullmatch(value) is not None


def credential_field(name: str, value: str) -> bool:
    """A structured field ``name: value`` that assigns a literal credential: the whole value is the finding."""
    match = _FIELD_NAME.match(name.strip())
    value = value.strip()
    return match is not None and len(value) >= 4 and _literal_value(match.group(1), value)


def find_credential_assignments(text: str) -> list[Finding]:
    found: list[Finding] = []
    for match in _matches(_ASSIGNMENT, text):
        name, value = match.group(1), match.group(2)
        if _literal_value(name, value):
            found.append(Finding(DETECTOR_CREDENTIAL_ASSIGNMENT, CATEGORY_SECRETS, CONFIDENCE_MEDIUM,
                                 match.start(2), match.end(2)))
    return found


def find_internal_ips(text: str) -> list[Finding]:
    found: list[Finding] = []
    for match in _matches(_IPV4, text):
        octets = match.group(0).split(".")
        if all(int(octet) <= 255 for octet in octets):
            found.append(Finding(DETECTOR_INTERNAL_IP, CATEGORY_INTERNAL_NETWORK, CONFIDENCE_MEDIUM,
                                 match.start(), match.end()))
    return found


def find_prompt_injection(text: str) -> list[Finding]:
    found = [Finding(DETECTOR_PROMPT_INJECTION, CATEGORY_PROMPT_INJECTION, CONFIDENCE_MEDIUM, match.start(),
                     match.end()) for pattern in _INJECTION for match in _matches(pattern, text)]
    found += [Finding(DETECTOR_PROMPT_INJECTION, CATEGORY_PROMPT_INJECTION, CONFIDENCE_MEDIUM, match.start(),
                      match.end()) for match in _matches(_ACT_AS, text)
              if match.group(1).lower() not in _ACT_AS_EXEMPT]
    return sorted(found, key=lambda item: item.start)


def is_role_phrasing(matched: str) -> bool:
    """Whether a ``prompt_injection`` finding's text is the role phrasing "act as <role>" (and nothing else)."""
    return _ROLE_PHRASING.fullmatch(matched) is not None


# Run after the ``builtin`` detectors, in this order, for every enabled id.
PLATFORM: dict[str, Callable[[str], list[Finding]]] = {
    DETECTOR_CREDENTIAL_ASSIGNMENT: find_credential_assignments,
    DETECTOR_INTERNAL_IP: find_internal_ips,
    DETECTOR_PROMPT_INJECTION: find_prompt_injection,
}


def find_platform(text: str, enabled: frozenset[str]) -> list[Finding]:
    """Every enabled platform detector over ``text``; raises ``builtin.CandidateLimitError``."""
    found: list[Finding] = []
    for detector_id, finder in PLATFORM.items():
        if detector_id in enabled:
            found.extend(finder(text))
    return found


__all__ = [
    "PLATFORM",
    "credential_field",
    "find_credential_assignments",
    "find_internal_ips",
    "find_platform",
    "find_prompt_injection",
    "is_role_phrasing",
]
