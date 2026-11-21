"""The closed contract of a workflow proposal: catalog, prompt, and strict answer validation.

The model receives the published workflow definitions (key, name, description, capability) and
the message, and must answer exactly::

    {"workflow_key": "<one of the catalog keys>" | null,
     "confidence": "low" | "medium" | "high",
     "requested": true | false,
     "reason": "<short>"}

``requested`` says whether the user's own words ask for the workflow's outcome; it is optional
(a weak model may drop it) and reads ``false`` when missing, so an unasked proposal never holds
the turn. Validation is otherwise strict and never guesses: a key outside the catalog is
``unknown_key`` (no proposal), a missing or unknown field or an out-of-vocabulary confidence is
``invalid_answer``.

The message reaches the model split into the user's instruction and the content quoted or pasted
inside it (``split_instruction``). Otherwise "Create ONE platform
work item ... and this description verbatim: <a description that mentions writing a
specification>" is proposed "spec-writing" with high confidence because of the payload, and the
turn is held. The classifier judges the instruction; quoted content follows after a marker,
shortened, as context only. This shortening applies to the classifier prompt alone: the turn
itself always gets the full message.
There is no keyword list, regex matching or scoring of the message here; the only decision
input is the model's structured answer against the closed catalog.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..prompt_catalog import render_prompt
from ..redaction_policy import redact_secret_text
from .explicit_selection import list_published_workflow_definitions
from .proposal_states import PROPOSAL_CONFIDENCES

PROPOSAL_CATALOG_MAX_ENTRIES = 24
PROPOSAL_CATALOG_MAX_TEXT_CHARS = 240
PROPOSAL_MESSAGE_MAX_CHARS = 4000
PROPOSAL_REASON_MAX_CHARS = 200
_ANSWER_FIELDS = frozenset({"workflow_key", "confidence", "reason"})
_OPTIONAL_ANSWER_FIELDS = frozenset({"requested"})
# Quoted content longer than this is moved out of the instruction; shorter quotes (a title) stay.
QUOTED_MIN_CHARS = 80
# A block after a line ending in ":" counts as pasted content from this length on.
PASTED_MIN_CHARS = 200
# Each quoted part is shown to the classifier shortened to this length (context, not instruction).
QUOTED_PREVIEW_CHARS = 240
_FENCED = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_QUOTED = re.compile(rf'"[^"\n]{{{QUOTED_MIN_CHARS},}}"|\u201c[^\u201d]{{{QUOTED_MIN_CHARS},}}\u201d')

ANSWER_INVALID = "invalid_answer"
ANSWER_UNKNOWN_KEY = "unknown_key"
ANSWER_NO_MATCH = "no_match"

# The answer contract the validator below parses (``_ANSWER_FIELDS``): a fixed protocol string, so it
# stays in code and fills ``{answer_contract}`` of the catalog key ``workflow.proposal.system_prompt``.
PROPOSAL_ANSWER_CONTRACT = (
    "Answer with exactly one JSON object and nothing else, with these fields: "
    '"workflow_key" (a catalog key or null), "confidence" ("low", "medium" or "high"), '
    '"requested" (true only when the user\'s own words ask for the outcome the workflow produces), '
    '"reason" (one short sentence in English explaining the choice). '
)


def proposal_system_prompt() -> str:
    return render_prompt("workflow.proposal.system_prompt", answer_contract=PROPOSAL_ANSWER_CONTRACT)


def _bounded(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


async def build_proposal_catalog(db: AsyncSession, *, project_id: str | None) -> list[dict[str, str]]:
    """Published definitions only, one entry per key, deterministically ordered and bounded."""
    catalog: list[dict[str, str]] = []
    seen: set[str] = set()
    for definition in await list_published_workflow_definitions(db, project_id=project_id):
        key = str(definition.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        entry = {
            "workflow_key": key,
            "name": _bounded(definition.get("title"), PROPOSAL_CATALOG_MAX_TEXT_CHARS),
            "description": _bounded(
                definition.get("when_to_use") or definition.get("description"), PROPOSAL_CATALOG_MAX_TEXT_CHARS
            ),
        }
        capability = str(definition.get("capability") or "").strip()
        if capability:
            entry["capability"] = capability
        catalog.append(entry)
    return catalog[:PROPOSAL_CATALOG_MAX_ENTRIES]


def _pasted_block_start(text: str) -> int | None:
    """Offset of a long block pasted after a line that ends with ":" (no keyword list)."""
    offset = 0
    for line in text.splitlines(keepends=True):
        offset += len(line)
        if line.rstrip().endswith(":") and len(text[offset:].strip()) >= PASTED_MIN_CHARS:
            return offset
    return None


def split_instruction(message: str) -> tuple[str, list[str]]:
    """The user's instruction, with long quoted or pasted parts replaced by ``[quoted text N]``.

    Structural only: fenced blocks, long quoted strings, and a long block after a line that ends
    with ":". The decision stays with the model; this only keeps a payload from posing as the ask.
    """
    quoted: list[str] = []

    def _take(part: str) -> str:
        quoted.append(part.strip())
        return f"[quoted text {len(quoted)}]"

    text = str(message or "")
    start = _pasted_block_start(text)
    tail = ""
    if start is not None:
        text, tail = text[:start], _take(text[start:])
    text = _FENCED.sub(lambda match: _take(match.group(0)), text)
    text = _QUOTED.sub(lambda match: _take(match.group(0)), text)
    if tail:
        # The pasted block is the last part of the message; number it after the inline quotes.
        quoted.append(quoted.pop(0))
        text = text.rstrip() + "\n" + f"[quoted text {len(quoted)}]"
    return text.strip(), quoted


def build_proposal_prompt(catalog: list[dict[str, str]], message: str) -> tuple[str, str]:
    system = proposal_system_prompt() + json.dumps(catalog, ensure_ascii=False, sort_keys=True)
    instruction, quoted = split_instruction(message)
    user = "User instruction:\n" + instruction[:PROPOSAL_MESSAGE_MAX_CHARS]
    if quoted:
        previews = "\n".join(
            f"[quoted text {index}]: {_bounded(part, QUOTED_PREVIEW_CHARS)}" for index, part in enumerate(quoted, 1)
        )
        user += "\n\nQuoted content inside the instruction (context only, not the request):\n" + previews
    return system, user


@dataclass(frozen=True, slots=True)
class ProposalAnswer:
    """A validated answer; ``outcome`` is ``None`` for a valid catalog key."""

    outcome: str | None
    workflow_key: str | None = None
    confidence: str | None = None
    reason: str | None = None
    requested: bool = False


def _clean_reason(value: Any) -> str | None:
    text = _bounded(redact_secret_text(value if isinstance(value, str) else ""), PROPOSAL_REASON_MAX_CHARS)
    return text or None


def validate_proposal_answer(answer: Any, catalog_keys: set[str]) -> ProposalAnswer:
    """Strictly validate the model's structured answer against the closed catalog."""
    if not isinstance(answer, dict) or not _ANSWER_FIELDS <= set(answer) <= _ANSWER_FIELDS | _OPTIONAL_ANSWER_FIELDS:
        return ProposalAnswer(ANSWER_INVALID)
    requested = answer.get("requested", False)
    if not isinstance(requested, bool):
        return ProposalAnswer(ANSWER_INVALID)
    confidence = answer.get("confidence")
    reason = answer.get("reason")
    key = answer.get("workflow_key")
    if confidence not in PROPOSAL_CONFIDENCES or not isinstance(reason, str):
        return ProposalAnswer(ANSWER_INVALID)
    clean_reason = _clean_reason(reason)
    if key is None:
        return ProposalAnswer(ANSWER_NO_MATCH, confidence=confidence, reason=clean_reason)
    if not isinstance(key, str) or key not in catalog_keys:
        # Never a guess: no normalization, no closest match, no retry.
        return ProposalAnswer(ANSWER_UNKNOWN_KEY, confidence=confidence, reason=clean_reason)
    return ProposalAnswer(None, workflow_key=key, confidence=confidence, reason=clean_reason, requested=requested)


__all__ = [
    "ANSWER_INVALID",
    "ANSWER_NO_MATCH",
    "ANSWER_UNKNOWN_KEY",
    "ProposalAnswer",
    "build_proposal_catalog",
    "build_proposal_prompt",
    "proposal_system_prompt",
    "split_instruction",
    "validate_proposal_answer",
]
