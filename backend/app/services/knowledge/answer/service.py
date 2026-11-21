"""The short cited answer on Knowledge Search.

The person's search found passages; the answer may only rest on those. The client sends their evidence keys, never
their text: each passage is read again with the reader's own Knowledge scope (``scoped_read``), so a key the reader
may not see, or that does not exist, is simply left out. The governed model answers from the numbered passages; the
validation keeps only sentences that cite them. Every outcome is a fixed state:

- ``ok`` — at least one cited sentence;
- ``no_answer`` — the passages do not answer the question (or nothing readable was sent);
- ``needs_configuration`` / ``denied`` — the model admission's state for this Workspace (data class, no runtime);
- ``unavailable`` — no admitted runtime gave a usable answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.bindings import KnowledgeScope
from ..ledger.errors import EvidenceLedgerError
from ..retrieval.scoped import scoped_read
from .model import AnswerModelUnavailableError, governed_answer_model
from .prompt import SYSTEM, answer_prompt
from .validate import cited_sentences

MAX_ANSWER_PASSAGES = 10
STATES = ("ok", "no_answer", "needs_configuration", "denied", "unavailable")


def _result(state: str, sentences: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sentences = sentences or []
    cited = list(dict.fromkeys(key for sentence in sentences for key in sentence["cites"]))
    return {"state": state, "sentences": sentences, "cited_keys": cited}


async def _readable_passages(
    db: AsyncSession, scope: KnowledgeScope, evidence_keys: Sequence[str]
) -> list[tuple[str, str, str]]:
    """``(evidence_key, title, text)`` for every key the reader may read, in the order sent."""

    passages: list[tuple[str, str, str]] = []
    for key in list(dict.fromkeys(evidence_keys))[:MAX_ANSWER_PASSAGES]:
        try:
            _held_by, read = await scoped_read(db, scope=scope, evidence_key=key, window=0)
        except EvidenceLedgerError:
            continue
        if read.text.strip():
            passages.append((read.evidence_key, read.source_title or "Untitled source", read.text))
    return passages


def _state_of(error: AnswerModelUnavailableError) -> str:
    return error.state if error.state in ("needs_configuration", "denied") else "unavailable"


async def answer_from_passages(
    db: AsyncSession, *, scope: KnowledgeScope, query_text: str, evidence_keys: Sequence[str]
) -> dict[str, Any]:
    question = query_text.strip()
    passages = await _readable_passages(db, scope, evidence_keys)
    if not question or not passages:
        return _result("no_answer")
    try:
        model = await governed_answer_model(db, project_id=scope.primary.project_id)
        answer = await model.json(
            system=SYSTEM, user=answer_prompt(question, [(title, text) for _key, title, text in passages])
        )
    except AnswerModelUnavailableError as error:
        return _result(_state_of(error))
    sentences = cited_sentences(answer, [key for key, _title, _text in passages])
    return _result("ok" if sentences else "no_answer", sentences)


__all__ = ["MAX_ANSWER_PASSAGES", "STATES", "answer_from_passages"]
