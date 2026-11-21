"""How far the content policies trust a system message of a model request.

Three levels; only the prompt builder sets the first two, on system messages
(``content_trust``: :func:`system_message`):

- ``platform_instruction`` — platform instruction text (catalog templates, mode definitions, precedence and fence
  lines): sent verbatim without checks only when its text is exactly a shipped seed text (by content hash,
  ``prompt_catalog.shipped_seed_text``: :func:`is_platform_instruction`); any other text with this marker — a
  rendered or composed section — is checked like ``authored`` text (:func:`checked_trust`);
- ``authored`` — administrator-authored governed text (the selected agent's blueprint and reply format, the
  Workspace workflow catalog, and every catalog-rendered section whose body is a published override instead of
  the shipped seed): masking and reporting apply, and so does the prompt-injection refusal, with one narrow
  exemption — **role phrasing** (``platform_detectors.is_role_phrasing``: only the owner-approved "Act as <role>"
  form, e.g. "Act as a senior SRE"). Every other injection finding in authored text ("ignore all previous
  instructions", "you are now", jailbreak, developer mode, "pretend to be") is refused like in untrusted input
  (:func:`without_role_phrasing`);
- untrusted (no marker, the default) — memory, entity context, compaction, checkpoint, repository knowledge, the
  person's communication preferences, loop reminders, and every user, assistant and tool message: refusal,
  masking and reporting.

A marker on any role other than ``system`` is ignored: the role alone never makes content trusted, and a marker
never trusts a non-system message. The marker is request metadata, not content: the model-call enforcement point
(``model_call``) removes it from the provider-bound copy, so no driver ever sends it.
"""

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
    """A system message of ``trust`` (an untrusted one carries no marker)."""
    message = {"role": "system", "content": content, **fields}
    if trust in _MARKED:
        message[CONTENT_TRUST_KEY] = trust
    return message


def platform_instruction(content: str, **fields: Any) -> dict[str, Any]:
    return system_message(content, TRUST_PLATFORM_INSTRUCTION, **fields)


def authored_instruction(content: str, **fields: Any) -> dict[str, Any]:
    return system_message(content, TRUST_AUTHORED, **fields)


def trust_of(message: Any) -> str:
    """The trust level of ``message``: a marker counts only on a system message."""
    if isinstance(message, Mapping) and message.get("role") == "system":
        marker = message.get(CONTENT_TRUST_KEY)
        if isinstance(marker, str) and marker in _MARKED:  # a marker of another shape is no marker
            return str(marker)
    return TRUST_UNTRUSTED


def is_platform_instruction(message: Any) -> bool:
    """A platform instruction whose text is exactly a shipped seed text: the only message the checks skip."""
    if trust_of(message) != TRUST_PLATFORM_INSTRUCTION:
        return False
    content = message.get("content")
    return isinstance(content, str) and shipped_seed_text(content)


def checked_trust(message: Any) -> str:
    """The trust a checked message is read with: a platform instruction that is not exactly a shipped seed text is
    read as administrator-authored text."""
    trust = trust_of(message)
    return TRUST_AUTHORED if trust == TRUST_PLATFORM_INSTRUCTION else trust


def without_role_phrasing(examination: Examination, segments: Sequence[Segment]) -> Examination:
    """``examination`` (of authored ``segments``) without its role-phrasing injection findings."""
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
