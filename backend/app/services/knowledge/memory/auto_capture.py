"""Automatic capture at turn end: a few memories the user explicitly stated, inferred by a governed model.

Off by default. It runs only when the Workspace row enables it (``settings``), only after a user-facing
turn has completed and been persisted, and never for a sub-agent turn. It reads the finished turn's
user-visible messages only (the last user message and the assistant answer after it; no tool results,
no system prompt), asks one bounded governed model call (``capture_model``) for at most
``MAX_CANDIDATES`` candidates, and writes each accepted one as ``model_inferred`` + ``observed`` for the
user to confirm, correct or forget.

A candidate is accepted only when

- its ``user_quote`` is a verbatim part of the user's message (so it is something the user stated,
  not something the assistant said or the model invented);
- its class is one capture may write (``personal`` and ``learning`` as personal memory; ``decision``
  and ``convention`` as Workspace memory, which needs the user's authoring role like an explicit
  ``memory_remember``);
- its text passes ``text_guard`` (bounds, visible characters, and the secret refusal);
- no visible item of the Workspace already has the same text, whatever its state: an inferred memory
  never duplicates, confirms or resurrects a corrected one.

It never fails the turn and never slows it: it runs at the end of the turn's background follow-up
(``services/session/turn_follow_up``), after the turn is committed, with the model's reply bounded by
``AUTO_CAPTURE_TIMEOUT_SECONDS``, and logs only fixed reason tokens. Only the reply is bounded: cancelling a
database call half way would leave the session's transaction broken and its connection held.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog import render_prompt
from app.services.prompt_catalog.out_of_turn import scoped_prompt_set

from ....models import Message
from ....models import Session as AgentSession
from ....models.project.knowledge_memory import KnowledgeMemoryItem, MemoryAuthorClass, MemoryClass, MemoryScope
from ..access.authorization import AuthorizedWorkspace, authorize_tool_workspace
from ..ledger.errors import EvidenceLedgerError
from .capture import MemoryProvenance, remember
from .capture_model import CaptureModelUnavailableError, governed_capture_model
from .errors import MemoryRefusedError
from .settings import automatic_capture_enabled
from .text_guard import content_hash, normalize_memory_text
from .visibility import visible_to

logger = logging.getLogger(__name__)

AUTO_CAPTURE_TIMEOUT_SECONDS = 30.0
MAX_CANDIDATES = 3
MAX_TURN_TEXT_CHARS = 6000
MIN_QUOTE_CHARS = 12
SCOPE_BY_CLASS = {
    MemoryClass.PERSONAL.value: MemoryScope.USER.value,
    MemoryClass.LEARNING.value: MemoryScope.USER.value,
    MemoryClass.DECISION.value: MemoryScope.WORKSPACE.value,
    MemoryClass.CONVENTION.value: MemoryScope.WORKSPACE.value,
}
_MODEL_STATES = frozenset({"needs_configuration", "denied", "unavailable"})
_WHITESPACE = re.compile(r"\s+")

# The JSON answer the capture parses: fixed protocol, fills ``{answer_contract}`` of
# ``knowledge.memory.capture_system``.
MEMORY_ANSWER_CONTRACT = (
    "Answer with one JSON object only: "
    '{"memories": [{"class": "personal|decision|convention|learning", "text": "the memory as one short '
    'sentence in the user\'s words", "user_quote": "the exact words of the user message that state it"}]} '
    f"with at most {MAX_CANDIDATES} memories."
)

@dataclass(frozen=True, slots=True)
class CaptureOutcome:
    reason: str
    recorded: int = 0
    skipped: int = 0


ModelFactory = Callable[..., Awaitable[Any]]


def _normalized(text: str) -> str:
    return _WHITESPACE.sub(" ", text.casefold()).strip()


def _bounded(text: str | None) -> str:
    return str(text or "").strip()[:MAX_TURN_TEXT_CHARS]


async def _finished_turn(db: AsyncSession, session_id: str) -> tuple[Message, Message | None] | None:
    user_message = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id, Message.role == "user")
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if user_message is None or not str(user_message.content or "").strip():
        return None
    answer = (
        (
            await db.execute(
                select(Message)
                .where(
                    Message.session_id == session_id,
                    Message.role == "assistant",
                    Message.created_at >= user_message.created_at,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return user_message, answer


def _turn_prompt(user_text: str, answer_text: str) -> str:
    return render_prompt("knowledge.memory.capture_turn", user_text=user_text, answer_text=answer_text or "(none)")


def accepted_candidates(answer: object, user_text: str) -> tuple[list[tuple[str, str]], int]:
    """The (class, text) pairs a model answer may write, and how many candidates were rejected."""
    raw = answer.get("memories") if isinstance(answer, dict) else None
    if not isinstance(raw, list):
        return [], 0
    stated = _normalized(user_text)
    accepted: list[tuple[str, str]] = []
    rejected = 0
    for candidate in raw[:MAX_CANDIDATES]:
        item_class = candidate.get("class") if isinstance(candidate, dict) else None
        text = candidate.get("text") if isinstance(candidate, dict) else None
        quote = candidate.get("user_quote") if isinstance(candidate, dict) else None
        if (
            type(item_class) is not str
            or item_class not in SCOPE_BY_CLASS
            or type(text) is not str
            or type(quote) is not str
            or len(_normalized(quote)) < MIN_QUOTE_CHARS
            or _normalized(quote) not in stated
        ):
            rejected += 1
            continue
        accepted.append((item_class, text))
    rejected += max(len(raw) - MAX_CANDIDATES, 0)
    return accepted, rejected


async def _already_known(db: AsyncSession, *, project_id: str, user_id: str, text: str) -> bool:
    digest = content_hash(text)
    row = await db.execute(
        select(KnowledgeMemoryItem.id)
        .where(visible_to(project_id, user_id), KnowledgeMemoryItem.content_hash == digest)
        .limit(1)
    )
    return row.scalar_one_or_none() is not None


async def capture_turn_memories(
    db: AsyncSession, *, session_id: str, model_factory: ModelFactory = governed_capture_model
) -> CaptureOutcome:
    """Capture the finished turn of this session, or say with one fixed reason why not. Flushes only."""
    session = await db.get(AgentSession, session_id)
    if session is None:
        return CaptureOutcome("no_session")
    if session.parent_session_id or int(session.sub_agent_depth or 0) > 0:
        return CaptureOutcome("sub_agent_turn")
    if not session.project_id:
        return CaptureOutcome("no_workspace")
    if not await automatic_capture_enabled(db, session.project_id):
        return CaptureOutcome("disabled")
    turn = await _finished_turn(db, session_id)
    if turn is None:
        return CaptureOutcome("no_turn")
    user_message, answer = turn
    try:
        authorized = await authorize_tool_workspace(
            db, user_id=str(session.user_id), project_id=session.project_id, allowed_project_ids=[session.project_id]
        )
    except EvidenceLedgerError:
        return CaptureOutcome("not_authorized")
    user_text = _bounded(user_message.content)
    try:
        async with scoped_prompt_set(db, workspace_id=authorized.project_id):
            system = render_prompt("knowledge.memory.capture_system", answer_contract=MEMORY_ANSWER_CONTRACT)
            user = _turn_prompt(user_text, _bounded(answer and answer.content))
        model = await model_factory(db, project_id=authorized.project_id)
        reply = await asyncio.wait_for(model.json(system=system, user=user), timeout=AUTO_CAPTURE_TIMEOUT_SECONDS)
    except CaptureModelUnavailableError as error:
        return CaptureOutcome(f"model_{error.state if error.state in _MODEL_STATES else 'unavailable'}")

    candidates, skipped = accepted_candidates(reply, user_text)
    provenance = MemoryProvenance(user_id=str(session.user_id), session_id=session_id, turn_ref=user_message.id)
    recorded, skipped = await _record_candidates(db, authorized, provenance, candidates, skipped)
    return CaptureOutcome("captured" if recorded else "nothing_to_capture", recorded=recorded, skipped=skipped)


async def _record_candidates(
    db: AsyncSession,
    authorized: AuthorizedWorkspace,
    provenance: MemoryProvenance,
    candidates: list[tuple[str, str]],
    skipped: int,
) -> tuple[int, int]:
    """Write each accepted candidate once; a refused, repeated or already known one only counts as skipped."""
    recorded = 0
    seen: set[str] = set()
    for item_class, text in candidates:
        try:
            body = normalize_memory_text(text)
        except MemoryRefusedError:
            skipped += 1
            continue
        digest = content_hash(body)
        if digest in seen or await _already_known(
            db, project_id=authorized.project_id, user_id=provenance.user_id, text=body
        ):
            skipped += 1
            continue
        seen.add(digest)
        try:
            await remember(
                db,
                authorized=authorized,
                provenance=provenance,
                text=body,
                scope=SCOPE_BY_CLASS[item_class],
                item_class=item_class,
                author_class=MemoryAuthorClass.MODEL_INFERRED,
            )
        except MemoryRefusedError:
            skipped += 1
            continue
        recorded += 1
    return recorded, skipped


async def run_turn_memory_capture(
    *, session_factory: Callable[[], Any], session_id: str, model_factory: ModelFactory = governed_capture_model
) -> CaptureOutcome:
    """The background entry point: bounded, never raising, logging only fixed reason tokens."""
    try:
        async with session_factory() as db:
            try:
                outcome = await capture_turn_memories(db, session_id=session_id, model_factory=model_factory)
            except TimeoutError:
                await db.rollback()
                outcome = CaptureOutcome("timeout")
            else:
                if outcome.recorded:
                    await db.commit()
                else:
                    await db.rollback()
    except Exception:  # noqa: BLE001 - capture must never fail the turn; no exception text is logged
        outcome = CaptureOutcome("failed")
    logger.info(
        "knowledge_memory_capture reason=%s recorded=%d skipped=%d", outcome.reason, outcome.recorded, outcome.skipped
    )
    return outcome


__all__ = [
    "AUTO_CAPTURE_TIMEOUT_SECONDS",
    "CaptureOutcome",
    "accepted_candidates",
    "capture_turn_memories",
    "run_turn_memory_capture",
]
