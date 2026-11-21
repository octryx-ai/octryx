"""The answer evidence check, its closed decision and the trace record.

Product rule: evidence is critical; every citation shows its source with a clickable URL.

:func:`check_answer_evidence` compares a final answer with the evidence of its turn
(``evidence.collect_turn_evidence``):

- ``cited_count`` / ``uncited_count``: the answer's statement blocks (``answer_blocks``) with and
  without a link to a URL from this turn's tool results (or an exact plain ``cite_as`` label);
- ``invented_urls``: answer links that appear neither in this turn's tool results nor in the user's
  own message.

The closed decision recorded on the turn trace (``answer_evidence.evidence_guard``):

- ``unsourced``: the turn's tool results carry no openable source, so the answer is not backed by
  this turn's evidence. It is delivered unchanged; the marker says so (a greeting, pure reasoning,
  or an answer from model knowledge).
- ``passed``: evidence-bearing turn, every statement cited, no invented link.
- ``reminded``: the reply failed the check and was suppressed with the one reminder.
- ``refused``: the reply failed again after the reminder; the user gets the explicit refusal.
- ``marked``: delivered with each uncited claim marked "no source" (see below).

Proportionate: a strict guard withholds answers whose drafts are right and linked, because an introduction
("Your branch naming rule is documented in ...") or a closing remark has no link of its own, or after a write was
already done the person only sees "withheld". A factual answer must cite its sources, but not every sentence. So:

- only a *claim* needs a citation: in an answer that links a source of this turn, its opening and closing paragraph
  frame the cited content and are not claims (an answer that links nothing has no frame: every statement is a claim);
- a turn that executed a write reports that action: its answer is delivered as it is;
- a claim without a source is marked, invented links are marked, and the answer is delivered (``mark_answer``); the
  whole answer is never withheld.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .answer_blocks import (
    AnswerBlock,
    answer_block_spans,
    answer_text_outside_code,
    asks_or_introduces,
    has_words,
    is_statement,
)
from .evidence import TurnEvidence
from .record import GUARD_STATES
from .texts import guard_text
from .urls import unique, urls_in_text

REFUSAL_REASON_UNCITED = "answer_evidence_uncited"
REFUSAL_REASON_INVENTED_URL = "answer_evidence_invented_url"
MAX_REPORTED_URLS = 5
MAX_REFUSAL_SOURCES = 8
MAX_UNCITED_BLOCKS = 16
MAX_UNCITED_BLOCK_CHARS = 400


@dataclass(frozen=True, slots=True)
class AnswerEvidenceCheck:
    evidence_bearing: bool
    evidence_url_count: int
    cited_count: int
    uncited_count: int
    invented_urls: tuple[str, ...]
    uncited_blocks: tuple[str, ...] = ()
    uncited_lines: tuple[int, ...] = ()
    links_a_source: bool = False
    reports_write: bool = False

    @property
    def satisfied(self) -> bool:
        return not self.evidence_bearing or (self.uncited_count == 0 and not self.invented_urls)

    @property
    def refusal_reason(self) -> str:
        return REFUSAL_REASON_INVENTED_URL if self.invented_urls else REFUSAL_REASON_UNCITED


def _cited(block: str, evidence: TurnEvidence) -> bool:
    if any(url in evidence.result_urls for url in urls_in_text(block)):
        return True
    return any(label in block for label in evidence.plain_labels)


def _claims(blocks: list[AnswerBlock], *, framed: bool) -> list[AnswerBlock]:
    """The statement blocks that need a source: an answer that links a source is framed by its first and last
    paragraph (an introduction, a closing offer), which are not claims of their own."""
    frame = {0, len(blocks) - 1} if framed and len(blocks) >= 2 else set()
    return [
        block
        for index, block in enumerate(blocks)
        if is_statement(block.text) and not (index in frame and block.kind == "paragraph")
    ]


def check_answer_evidence(answer: str, evidence: TurnEvidence, *, user_message: str = "") -> AnswerEvidenceCheck:
    """Compare ``answer`` with this turn's evidence; structural only, never the meaning of the text."""
    text = answer_text_outside_code(answer)
    blocks = answer_block_spans(answer)
    links_a_source = any(_cited(block.text, evidence) for block in blocks)
    claims = _claims(blocks, framed=links_a_source)
    stating = [block for block in blocks if not asks_or_introduces(block.text)]
    if not claims and not links_a_source and stating and has_words(text):
        # A short answer that links nothing is still one statement: it must link its source too (a question back
        # needs none).
        claims = [AnswerBlock(text, blocks[-1].last_line, "paragraph")]
    uncited = [block for block in claims if not _cited(block.text, evidence)]
    allowed = evidence.result_urls | frozenset(urls_in_text(user_message))
    invented = tuple(url for url in unique(urls_in_text(text)) if url not in allowed)
    return AnswerEvidenceCheck(
        evidence_bearing=evidence.evidence_bearing,
        evidence_url_count=len(evidence.evidence_urls),
        cited_count=len(claims) - len(uncited),
        uncited_count=len(uncited),
        invented_urls=invented,
        uncited_blocks=tuple(block.text[:MAX_UNCITED_BLOCK_CHARS] for block in uncited)[:MAX_UNCITED_BLOCKS],
        uncited_lines=tuple(block.last_line for block in uncited),
        links_a_source=links_a_source,
        reports_write=bool(evidence.executed_writes),
    )


def _with_marker(line: str, marker: str) -> str:
    stripped = line.rstrip()
    if stripped.endswith("|") and stripped.lstrip().startswith("|"):
        # A table row keeps its closing pipe: the marker goes into the last cell.
        return f"{stripped[:-1].rstrip()} {marker} |"
    return f"{stripped} {marker}"


def mark_answer(answer: str, check: AnswerEvidenceCheck, evidence: TurnEvidence) -> str:
    """The answer as delivered when it falls short: nothing removed, each shortfall marked in place.

    - an answer that links some source: each uncited claim gets the "no source" marker;
    - an answer that links nothing: one closing note with the sources this turn found, instead of a marker on every
      paragraph;
    - invented links: one closing note naming them.
    """
    lines = str(answer or "").splitlines()
    notes: list[str] = []
    if check.uncited_count and check.links_a_source:
        marker = guard_text("evidence_guard.mark.uncited")
        for index in set(check.uncited_lines):
            if 0 <= index < len(lines):
                lines[index] = _with_marker(lines[index], marker)
    elif check.uncited_count:
        sources = ", ".join(source.cite_as for source in evidence.linkable[:MAX_REFUSAL_SOURCES])
        notes.append(guard_text("evidence_guard.mark.unlinked", sources=sources))
    if check.invented_urls:
        urls = ", ".join(check.invented_urls[:MAX_REPORTED_URLS])
        notes.append(guard_text("evidence_guard.mark.invented", urls=urls))
    return "\n\n".join(["\n".join(lines), *notes]) if notes else "\n".join(lines)


def answer_evidence_record(state: str, check: AnswerEvidenceCheck, *, reminder_count: int) -> dict[str, Any]:
    """The closed trace record: the decision and bounded counts, never answer text or URLs."""
    if state not in GUARD_STATES:
        raise ValueError("unknown evidence guard state")
    return {
        "evidence_guard": state,
        "cited_count": check.cited_count,
        "uncited_count": check.uncited_count,
        "invented_url_count": len(check.invented_urls),
        "evidence_url_count": check.evidence_url_count,
        "reminder_count": reminder_count,
    }


def evidence_reminder(check: AnswerEvidenceCheck) -> str:
    details: list[str] = []
    if check.uncited_count:
        details.append(guard_text("evidence_guard.reminder.uncited", count=check.uncited_count))
    if check.invented_urls:
        urls = ", ".join(check.invented_urls[:MAX_REPORTED_URLS])
        details.append(guard_text("evidence_guard.reminder.invented", urls=urls))
    if check.uncited_blocks:
        details.append(json.dumps({"uncited_blocks": check.uncited_blocks}, ensure_ascii=True))
    return guard_text("evidence_guard.reminder", details=" ".join(details))


def evidence_refusal(check: AnswerEvidenceCheck, evidence: TurnEvidence) -> str:
    details: list[str] = []
    if check.uncited_count:
        details.append(guard_text("evidence_guard.refusal.uncited", count=check.uncited_count))
    if check.invented_urls:
        details.append(guard_text("evidence_guard.refusal.invented", count=len(check.invented_urls)))
    message = guard_text("evidence_guard.refusal", details=" ".join(details))
    sources = [f"- {source.cite_as}" for source in evidence.linkable[:MAX_REFUSAL_SOURCES]]
    if not sources:
        return message
    return "\n\n".join([message, guard_text("evidence_guard.refusal.sources"), "\n".join(sources)])


__all__ = [
    "REFUSAL_REASON_INVENTED_URL",
    "REFUSAL_REASON_UNCITED",
    "AnswerEvidenceCheck",
    "answer_evidence_record",
    "check_answer_evidence",
    "evidence_refusal",
    "evidence_reminder",
    "mark_answer",
]
