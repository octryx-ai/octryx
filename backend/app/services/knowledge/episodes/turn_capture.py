"""Automatic episode capture at the end of a platform chat turn (open point K1a).

Off by default. It runs only when the Workspace row sets both
``knowledge_episode_policy.accept_session_episodes`` and ``capture_platform_turns`` to an explicit
``true`` (``policy.py``), only after a user-facing turn has completed and been persisted, and never
for a sub-agent turn. It uses the same post-turn hook as the Memory capture
(``services/session/turn_follow_up.run_completion_follow_up``): after the turn is committed, as a
background task, bounded by ``EPISODE_CAPTURE_TIMEOUT_SECONDS``, never raising, logging only fixed
reason tokens.

**What the model sees.** Only user-visible text: the turn's user message, its final assistant
answer, the sources that answer cites (its markdown links), and the session's current episode
summary so the new one updates it instead of starting over. No tool call, tool result, system
prompt or trace is ever read. Every input is redacted by the episode redaction before the call.

**What is written.** The governed model call (dispatch owner ``knowledge_episode_summary``) answers
one updated session summary, which goes through the same governed writer as the REST endpoint and
the chat tool (``writer.record_episode_summary``): role, switch, public origin, bounds, redaction,
and deduplication by digest (an unchanged summary is ``duplicate`` and writes nothing).

**Once per answer.** When the session's episode already has a revision recorded after this turn's
answer, the turn was captured already and no model call is made.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog import render_prompt
from app.services.prompt_catalog.out_of_turn import scoped_prompt_set

from ....models import Message
from ....models import Session as AgentSession
from ....models.project.knowledge_evidence import KnowledgeSourceRevision
from ..access.authorization import AuthorizedWorkspace, authorize_tool_workspace
from ..ledger.errors import EvidenceLedgerError
from ..memory.capture_model import CaptureModelUnavailableError
from .policy import EPISODE_WRITER_ROLES, platform_turn_capture_enabled, public_origin
from .redaction import redact_episode_text
from .summary_model import governed_summary_model
from .turn_reads import (
    _finished_turn,
    _latest_episode,
    _summary_text,
)
from .writer import EpisodeProvenance, record_episode_summary

logger = logging.getLogger(__name__)

EPISODE_CAPTURE_TIMEOUT_SECONDS = 45.0
PLATFORM_CLIENT = "platform"
MAX_QUESTION_CHARS = 2000
MAX_ANSWER_CHARS = 6000
MAX_CITED_SOURCES = 12
_MODEL_STATES = frozenset({"needs_configuration", "denied", "unavailable"})
_WRITTEN = frozenset({"recorded", "duplicate"})
# A markdown link with an absolute http(s) target: how every governed citation (cite_as) is written.
_CITATION = re.compile(r"\[([^\[\]\n]{1,300})\]\((https?://[^\s()<>]{1,2048})\)")

# The JSON answer the capture parses: fixed protocol, fills ``{answer_contract}`` of
# ``knowledge.episode.system``.
EPISODE_ANSWER_CONTRACT = (
    'Answer with one JSON object only: {"title": "a short title of the session", "summary": '
    '"the updated summary"}.'
)


@dataclass(frozen=True, slots=True)
class EpisodeCaptureOutcome:
    reason: str
    revision: int | None = None


ModelFactory = Callable[..., Awaitable[Any]]


def cited_sources(answer: str) -> list[tuple[str, str]]:
    """The (title, url) pairs the answer cites as markdown links, in order, deduplicated, bounded."""
    seen: set[str] = set()
    cited: list[tuple[str, str]] = []
    for title, url in _CITATION.findall(answer):
        if url in seen:
            continue
        seen.add(url)
        cited.append((" ".join(title.split()), url))
        if len(cited) >= MAX_CITED_SOURCES:
            break
    return cited


def _redacted(text: object, limit: int) -> str:
    return redact_episode_text(str(text or "").strip()[:limit]).text


def _turn_prompt(previous: str, question: str, answer: str, sources: list[tuple[str, str]]) -> str:
    listed = "\n".join(f"- [{title}]({url})" for title, url in sources) or "(none)"
    return render_prompt(
        "knowledge.episode.turn",
        previous=previous or "(empty)",
        question=question or "(none)",
        answer=answer,
        sources=listed,
    )


async def _authorized_capture(db: AsyncSession, session: AgentSession) -> AuthorizedWorkspace | EpisodeCaptureOutcome:
    """The session's Workspace authorization when this turn may be captured, else the reason it may not."""
    if session.parent_session_id or int(session.sub_agent_depth or 0) > 0:
        return EpisodeCaptureOutcome("sub_agent_turn")
    if not session.project_id:
        return EpisodeCaptureOutcome("no_workspace")
    if not await platform_turn_capture_enabled(db, session.project_id):
        return EpisodeCaptureOutcome("disabled")
    if public_origin() is None:
        return EpisodeCaptureOutcome("public_origin_missing")
    try:
        authorized = await authorize_tool_workspace(
            db, user_id=str(session.user_id), project_id=session.project_id, allowed_project_ids=[session.project_id]
        )
    except EvidenceLedgerError:
        return EpisodeCaptureOutcome("not_authorized")
    if authorized.role not in EPISODE_WRITER_ROLES:
        return EpisodeCaptureOutcome("role_required")
    return authorized


async def _summarize_turn(
    db: AsyncSession,
    authorized: AuthorizedWorkspace,
    latest: KnowledgeSourceRevision | None,
    turn: tuple[Message, Message],
    model_factory: ModelFactory,
) -> Any:
    """The model's reply for the redacted turn, or the outcome when no model could be used."""
    question, answer = turn
    answer_text = _redacted(answer.content, MAX_ANSWER_CHARS)
    summary_text = await _summary_text(db, latest)
    async with scoped_prompt_set(db, workspace_id=authorized.project_id):
        prompt = _turn_prompt(
            summary_text,
            _redacted(question.content, MAX_QUESTION_CHARS),
            answer_text,
            cited_sources(answer_text),
        )
        system = render_prompt("knowledge.episode.system", answer_contract=EPISODE_ANSWER_CONTRACT)
    try:
        model = await model_factory(db, project_id=authorized.project_id)
        reply = await model.json(system=system, user=prompt)
    except CaptureModelUnavailableError as error:
        return EpisodeCaptureOutcome(f"model_{error.state if error.state in _MODEL_STATES else 'unavailable'}")
    return reply


async def capture_turn_episode(
    db: AsyncSession, *, session_id: str, model_factory: ModelFactory = governed_summary_model
) -> EpisodeCaptureOutcome:
    """Write or update this session's episode from its finished turn, or say why not. Flushes only."""
    session = await db.get(AgentSession, session_id)
    if session is None:
        return EpisodeCaptureOutcome("no_session")
    authorized = await _authorized_capture(db, session)
    if isinstance(authorized, EpisodeCaptureOutcome):
        return authorized
    turn = await _finished_turn(db, session_id)
    if turn is None:
        return EpisodeCaptureOutcome("no_turn")
    question, answer = turn
    latest = await _latest_episode(db, authorized.project_id, str(session.id))
    if latest is not None and answer.created_at is not None and latest.created_at >= answer.created_at:
        return EpisodeCaptureOutcome("already_captured", revision=int(latest.revision_ordinal))

    reply = await _summarize_turn(db, authorized, latest, turn, model_factory)
    if isinstance(reply, EpisodeCaptureOutcome):
        return reply
    summary = reply.get("summary") if isinstance(reply, dict) else None
    if type(summary) is not str or not summary.strip():
        return EpisodeCaptureOutcome("nothing_to_summarize")
    title = reply.get("title") if isinstance(reply.get("title"), str) else None
    result = await record_episode_summary(
        db,
        authorized=authorized,
        provenance=EpisodeProvenance(
            session_id=str(session.id),
            client=PLATFORM_CLIENT,
            recorded_by=str(session.user_id),
            session_date=session.started_at.date().isoformat() if session.started_at else "",
        ),
        summary=summary,
        title=title,
    )
    state = str(result.get("state"))
    if state not in _WRITTEN:
        return EpisodeCaptureOutcome(str(result.get("reason") or state))
    revision = result.get("revision")
    return EpisodeCaptureOutcome(state, revision=int(revision) if isinstance(revision, int) else None)


async def run_turn_episode_capture(
    *, session_factory: Callable[[], Any], session_id: str, model_factory: ModelFactory = governed_summary_model
) -> EpisodeCaptureOutcome:
    """The background entry point: bounded, never raising, logging only fixed reason tokens."""
    try:
        async with session_factory() as db:
            try:
                outcome = await asyncio.wait_for(
                    capture_turn_episode(db, session_id=session_id, model_factory=model_factory),
                    timeout=EPISODE_CAPTURE_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                await db.rollback()
                outcome = EpisodeCaptureOutcome("timeout")
            else:
                if outcome.reason == "recorded":
                    await db.commit()
                else:
                    await db.rollback()
    except Exception:  # noqa: BLE001 - capture must never fail the turn; no exception text is logged
        outcome = EpisodeCaptureOutcome("failed")
    logger.info("knowledge_episode_capture reason=%s", outcome.reason)
    return outcome


__all__ = [
    "EPISODE_CAPTURE_TIMEOUT_SECONDS",
    "EpisodeCaptureOutcome",
    "capture_turn_episode",
    "cited_sources",
    "run_turn_episode_capture",
]
