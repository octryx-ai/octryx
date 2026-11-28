"""How far the content policies trust a system message of a model request."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..content_detection.examination import Examination
from ..content_detection.findings import Finding
from ..content_detection.platform_detectors import is_role_phrasing
from ..content_detection.scanner import Segment
from ..content_detection.vocabulary import DETECTOR_PROMPT_INJECTION
from ..prompt_catalog import shipped_seed_text

CONTENT_TRUST_KEY = "content_trust"
TRUST_PLATFORM_INSTRUCTION = "platform_instruction"
TRUST_AUTHORED = "authored"
TRUST_UNTRUSTED = "untrusted"
_MARKED = frozenset({TRUST_PLATFORM_INSTRUCTION, TRUST_AUTHORED})


def system_message(content: str, trust: str, **fields: Any) -> dict[str, Any]:
    message = {"role": "system", "content": content, **fields}
    if trust in _MARKED:
        message[CONTENT_TRUST_KEY] = trust
    return message


def platform_instruction(content: str, **fields: Any) -> dict[str, Any]:
    return system_message(content, TRUST_PLATFORM_INSTRUCTION, **fields)


def authored_instruction(content: str, **fields: Any) -> dict[str, Any]:
    return system_message(content, TRUST_AUTHORED, **fields)


# The role alone never trusts content, and a marker never trusts a non-system message.
def trust_of(message: Any) -> str:
    if isinstance(message, Mapping) and message.get("role") == "system":
        marker = message.get(CONTENT_TRUST_KEY)
        if isinstance(marker, str) and marker in _MARKED:  # a marker of another shape is no marker
            return str(marker)
    return TRUST_UNTRUSTED


def is_platform_instruction(message: Any) -> bool:
    if trust_of(message) != TRUST_PLATFORM_INSTRUCTION:
        return False
    content = message.get("content")
    return isinstance(content, str) and shipped_seed_text(content)


def checked_trust(message: Any) -> str:
    trust = trust_of(message)
    return TRUST_AUTHORED if trust == TRUST_PLATFORM_INSTRUCTION else trust


def without_role_phrasing(examination: Examination, segments: Sequence[Segment]) -> Examination:
    def exempt(index: int, item: Finding) -> bool:
        return (item.detector == DETECTOR_PROMPT_INJECTION
                and is_role_phrasing(segments[index].text[item.start:item.end]))

    return examination.excluding(exempt)


__all__ = [
    "CONTENT_TRUST_KEY",
    "TRUST_AUTHORED",
    "TRUST_PLATFORM_INSTRUCTION",
    "TRUST_UNTRUSTED",
    "authored_instruction",
    "checked_trust",
    "is_platform_instruction",
    "platform_instruction",
    "system_message",
    "trust_of",
    "without_role_phrasing",
]
