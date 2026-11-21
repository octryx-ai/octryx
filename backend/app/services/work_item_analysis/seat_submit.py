"""``work_item_analysis_submit``: store the analysis a seat analysis session wrote.

The caller is the MCP connection of a seat analysis session (``seat_session``): its launcher session key
(``X-Octryx-Session``, a transport setting, never a tool argument) names the registered session, which
must belong to the caller, be active, run the ``seat`` profile and be pinned to a work item the caller's grant
reaches. The Workspace must still allow seat (seat policy, classification included) and still select
``runner: seat``. Every refusal is a fixed code and stores nothing.

The analysis passes exactly the governed runner's contract: ``contract.parse_analysis`` (the
``incident_analysis_v1`` schema), ``contract.check_citations`` against the tool results the gateway observed
in this session, and the secret scan of the rendered note. A refused analysis is answered with its code and
stores nothing, so the session can fix it and submit again.

A valid analysis is stored like a governed one: a ``work_item_analysis`` row (``runner: seat``, the session's
model, platform cost 0), the agent note (``kind: analysis``), the board ``info`` and the optional reporter
question. The same ``active_key`` as the governed runner makes it one analysis per item version: an
existing one is answered with ``reused: true``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, Project, Session, User, WorkItem, WorkItemAnalysis
from ...time_utils import utc_now
from ..agent_gateway.seat_policy import workspace_seat_decision
from ..mcp_work_access import WorkGrantScope, scoped_work_item
from ..model_gateway.inbound.secret_scan import contains_secret
from ..policy_engine.request_principal import load_seat_principal
from .contract import AnalysisContractError, check_citations, parse_analysis, render_note
from .prompt import TEMPLATE_KEY, item_version, template_digest
from .records import append_analysis_note, post_analysis_info
from .reporter_questions import ask_reporter
from .runner import (
    AUDIT_FINISHED,
    AUDIT_STARTED,
    CONTENT_IS_DATA,
    MODE_MANUAL,
    STATUS_SUCCEEDED,
    analysis_view,
    audit_analysis,
)
from .seat_session import SESSION_TOOLS, observed_tool_outputs, pinned_item_id
from .settings import RUNNER_SEAT, settings_from_config

STATE_REFUSED = "refused"
CODE_SESSION_REQUIRED = "seat_analysis_session_required"
CODE_RUNNER_NOT_SEAT = "analysis_runner_not_seat"
CODE_SECRET = "secret_detected"
MAX_ANALYSIS_CHARS = 60_000


class SeatSubmitRefusal(Exception):  # noqa: N818 - a coded outcome, not an error
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _refused(code: str) -> dict[str, Any]:
    return {"status": STATE_REFUSED, "error_code": code, "stored": False, "content_is_data": CONTENT_IS_DATA}


async def _seat_session(db: AsyncSession, user: User, session_key: str | None) -> tuple[AgentPresence, Session]:
    if not session_key:
        raise SeatSubmitRefusal(CODE_SESSION_REQUIRED)
    presence = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == session_key))
                ).scalar_one_or_none()
    if presence is None or presence.user_id != user.id or presence.stopped_at is not None:
        raise SeatSubmitRefusal(CODE_SESSION_REQUIRED)
    session = await db.get(Session, presence.session_id) if presence.session_id else None
    if presence.profile != RUNNER_SEAT or pinned_item_id(session) is None:
        raise SeatSubmitRefusal(CODE_SESSION_REQUIRED)
    return presence, session


async def _workspace_allows(db: AsyncSession, item: WorkItem, user: User, session: Any, presence: Any) -> Any:
    # The seat is decided for this user and this seat session.
    principal = await load_seat_principal(user.id, session_id=session.id, client=str(presence.client or ""))
    seat = await workspace_seat_decision(db, item.project_id, principal=principal)
    if not seat.allowed:
        raise SeatSubmitRefusal(seat.reason or "seat_mode_forbidden")
    project = await db.get(Project, item.project_id)
    settings, _source = settings_from_config(project.config if project is not None else None)
    if settings.runner != RUNNER_SEAT:
        raise SeatSubmitRefusal(CODE_RUNNER_NOT_SEAT)
    return settings


def _parsed(raw: Any, outputs: list[str]) -> tuple[dict[str, Any], str]:
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, default=str)
    if len(text) > MAX_ANALYSIS_CHARS:
        raise AnalysisContractError("analysis_invalid")
    analysis = check_citations(parse_analysis(text), outputs)
    note = render_note(analysis, template=TEMPLATE_KEY)
    if contains_secret(note):
        raise AnalysisContractError(CODE_SECRET)
    return analysis, note


async def submit_seat_analysis(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, session_key: str | None, analysis: Any
) -> dict[str, Any]:
    """Validate and store one seat analysis; a refusal answers ``{status: refused, error_code}``. Commits."""
    try:
        presence, session = await _seat_session(db, user, session_key)
        item = await scoped_work_item(db, scope, pinned_item_id(session))
        settings = await _workspace_allows(db, item, user, session, presence)
        parsed, note = _parsed(analysis, await observed_tool_outputs(db, session.id))
    except SeatSubmitRefusal as refusal:
        return _refused(refusal.code)
    except AnalysisContractError as error:
        return _refused(error.code)
    key = f"{item.id}:{item_version(item)}:{TEMPLATE_KEY}"
    row = WorkItemAnalysis(project_id=item.project_id, work_item_id=item.id, item_version=item_version(item),
                           template=TEMPLATE_KEY, active_key=key, mode=MODE_MANUAL, status=STATUS_SUCCEEDED,
                           runner=RUNNER_SEAT, model=(presence.model or None), requested_by=user.id,
                           session_id=session.id, cost_usd=Decimal("0"), tokens_in=0, tokens_out=0,
                           analysis_json=parsed, created_at=utc_now(),
                           tools_json={"offered": list(SESSION_TOOLS), "unavailable": [],
                                       "template_digest": template_digest()})
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:  # this item version is analysed (or being analysed) already
        held = (await db.execute(select(WorkItemAnalysis).where(WorkItemAnalysis.active_key == key))
                ).scalar_one_or_none()
        return analysis_view(held, reused=True) if held is not None else _refused("analysis_slot_busy")
    audit_analysis(db, AUDIT_STARTED, user.id, row, item_version=row.item_version, runner=RUNNER_SEAT)
    await append_analysis_note(db, item=item, analysis=row, user=user, text=note, summary=parsed["summary"])
    message = await post_analysis_info(db, item=item, analysis=row, user=user, summary=parsed["summary"])
    row.board_message_id = message.id
    row.reporter_question = await ask_reporter(db, item=item, analysis=row, ask=settings.ask_reporter,
                                               actor_id=user.id)
    row.finished_at = utc_now()
    audit_analysis(db, AUDIT_FINISHED, user.id, row, status=row.status, error_code=None, cost_usd=0.0,
                   runner=RUNNER_SEAT, model=row.model, reporter_question=row.reporter_question)
    await db.commit()
    return {**analysis_view(row), "stored": True}


__all__ = ["CODE_RUNNER_NOT_SEAT", "CODE_SESSION_REQUIRED", "submit_seat_analysis"]
