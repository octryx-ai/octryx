"""What Allow on a chat's phased start does: the Jira issue, the Work item, the run (``phased_start``).

The steps run in order and each one's result is kept on the proposal record (``started``) as soon as it exists:

1. the Jira issue when the card's scope holds one (``phased_start_jira``); when Jira fails, the item is a platform
   item and the run still starts;
2. the Work item: the existing one, the item linked to the new issue, or a new platform item;
3. the run, exactly like the Work item dialog (``POST /api/v1/workflow-runs``: a new chat session, ``start_run`` with
   the confirmed location and repository).

A start whose run did not start (``started.error``: no repository, the item or the run refused) is tried again by the
next Allow (:func:`retry_phased_start`), so a second Allow after a failed start
does not pass without doing anything. A typed refusal also records ``started.state`` and ``started.reason`` (a chat
without a Workspace: ``needs_configuration`` / ``workspace_required``, refused before anything is created); its text
says what to configure instead of "Press Start again".
A retry reuses what exists (the Jira issue, the Work item), never creates it twice.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, User, WorkItem
from ...models import Session as AgentSession
from .phased_start import _PLATFORM_TYPE, _text, build_start_draft, update_proposal

logger = logging.getLogger(__name__)

# The runs a session's phased starts started, by proposal id: the held turn's summary reads "started" from it even
# after a later turn replaced the proposal record.
STARTS_METADATA_KEY = "workflow_proposal_starts"
MAX_RECORDED_STARTS = 20
DECISION_APPLY = "apply"
DECISION_SKIP = "skip"
HELD_MESSAGE_FIELD = "held_message_id"  # the held request's user message: the Jira write plan is bound to it


async def _chosen_target(db: AsyncSession, user: User, start: dict[str, Any]) -> dict[str, Any] | None:
    """The run location the person confirmed (the card's choice, else its default), as ``start_run`` takes it."""
    from ..workflow_runs.runtime_target.target import target_options

    key = _text(start["run_on"].get("chosen")) or _text(start["run_on"].get("default"))
    target = next((option["target"] for option in await target_options(db, user=user) if option["key"] == key), None)
    model = _text(start["run_on"].get("model"))
    if target is not None and model and target.get("kind") == "device":
        # The card's model for a device run (chosen at the chat
        # start); the epic chain passes it on to every story run. Validated again by the run start.
        target = {**target, "model": model}
    return target


async def _new_item(db: AsyncSession, user: User, start: dict[str, Any], jira: dict[str, Any] | None) -> WorkItem:
    from ..secure_work.platform_items import create_platform_work_item
    from .phased_start_jira import chat_workspace_item, jira_work_item

    item = start["work_item"]
    if item["mode"] == "existing" and item.get("id"):
        found = await chat_workspace_item(db, user, _text(start.get("project_id")), await db.get(WorkItem, item["id"]))
        if found is not None:
            return found
    if item["mode"] == "existing" and item.get("key"):
        return await _linked_item(db, user, start)
    if jira and jira.get("key"):
        return await jira_work_item(db, user=user, project_id=_text(start.get("project_id")), item=item, jira=jira)
    return await create_platform_work_item(
        db, current_user=user, project_id=_text(start.get("project_id")), title=item["title"] or start["summary"],
        description=item["description"], issue_type=_PLATFORM_TYPE.get(item["type"], item["type"]))


async def _linked_item(db: AsyncSession, user: User, start: dict[str, Any]) -> WorkItem:
    """The existing Jira issue the card bound by key (``phased_start._jira_item_view``): linked, never created.

    The item the Jira sync stored meanwhile is that item; otherwise it is linked
    like the sync stores it. No Jira issue and no second item are created for a key that exists.
    """
    from ..work_item_analysis.seat_session import items_by_key
    from .phased_start_jira import jira_work_item

    item, project_id = start["work_item"], _text(start.get("project_id"))
    synced = await items_by_key(db, project_id, item["key"])
    if len(synced) == 1:
        return synced[0]
    jira = {"key": item["key"], "id": None, "project_key": item["key"].rsplit("-", 1)[0],
            "issue_type": item["type_label"]}
    return await jira_work_item(db, user=user, project_id=project_id, item=item, jira=jira)


def _refusal_text(error: Exception) -> str:
    detail = getattr(error, "detail", None)
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("code")
    return _text(detail) or _text(error) or type(error).__name__


async def _session(db: AsyncSession, session_id: str) -> AgentSession:
    session = await db.get(AgentSession, session_id)
    await db.refresh(session)
    return session


async def _keep(db: AsyncSession, session_id: str, progress: dict[str, Any]) -> AgentSession:
    """Record what exists so far, before the next step can fail."""
    session = await _session(db, session_id)
    update_proposal(session, started=dict(progress))
    await db.commit()
    return session


async def _jira_step(db: AsyncSession, session_id: str, owner_id: str, start: dict[str, Any],
                     progress: dict[str, Any], approval_id: str | None) -> None:
    from .phased_start_jira import create_jira_issue

    done = progress.get("jira") or {}
    if not start.get("jira") or done.get("key") or progress.get("work_item_id"):
        return  # no issue in scope, or it (or the platform item after a failed Jira call) exists already
    session = await _session(db, session_id)
    progress["jira"] = await create_jira_issue(
        db, session=session, owner_id=owner_id, jira=start["jira"], description=start["work_item"]["description"],
        approval_id=approval_id, user_message_id=_held_message_id(session))
    await _keep(db, session_id, progress)


def _held_message_id(session: AgentSession) -> str:
    from .phased_start import _proposal

    return _text((_proposal(session) or {}).get(HELD_MESSAGE_FIELD))


async def _item_step(db: AsyncSession, session_id: str, user: User, start: dict[str, Any],
                     progress: dict[str, Any]) -> WorkItem:
    from fastapi import HTTPException

    found = await db.get(WorkItem, _text(progress.get("work_item_id"))) if progress.get("work_item_id") else None
    if found is not None:
        return found
    try:
        async with db.begin_nested():  # a savepoint: the caller's objects (the decided approval) stay loaded
            item = await _new_item(db, user, start, progress.get("jira"))
    except HTTPException as error:
        raise _StepFailedError(_refusal_text(error)) from error
    progress.update(work_item_id=item.id, work_item_key=item.source_key)
    await db.commit()
    await _keep(db, session_id, progress)
    return await db.get(WorkItem, progress["work_item_id"])


async def _budget_step(db: AsyncSession, user: User, start: dict[str, Any], item: WorkItem) -> None:
    """The card's budget onto the Work item before its run starts (a new
    epic has no item to set it on before the start). A patch like the limits PUT: the item's other limits stay; its
    stories inherit it. Only for an item in the person's Workspaces, like the limits route."""
    budget = start.get("budget")
    if not isinstance(budget, dict) or not budget:
        return
    from ..secure_work.access import work_item_in_scope, work_scope_project_ids
    from ..workflow_runs.limits import patch_run_limits

    if not work_item_in_scope(await work_scope_project_ids(db, user), item):
        raise _StepFailedError("The budget could not be set: the Work item is outside your Workspaces.")
    try:
        item.run_limits = patch_run_limits(item.run_limits, {"budget": budget}) or None
    except ValueError as error:
        raise _StepFailedError(f"The budget could not be set: {error}") from error
    await db.commit()


async def _run_step(db: AsyncSession, user: User, start: dict[str, Any], item: WorkItem,
                    progress: dict[str, Any]) -> None:
    from fastapi import HTTPException

    from ..workflow_runs import records

    target = await _chosen_target(db, user, start)
    # Never inside a savepoint: the run's first steps commit on their own (a platform action's tool records its
    # connection's health with a commit, ``circuit_breaker``; an external step commits its lease), and a commit
    # closes the savepoint. A refusal removes the run's chat session instead (it never stays without its run), and
    # nothing else is rolled back (a full rollback would expire the decided approval the caller still reads).
    run_session = await records.new_chat_session(db, user, item.project_id)
    try:
        run = await records.start_run(
            db, user=user, workflow_key=start["workflow_key"], project_id=item.project_id, work_item_id=item.id,
            session=run_session, runtime_target=target,
            repository=_text(dict(start.get("repository") or {}).get("ref")) or None)
    except (records.WorkflowRunError, HTTPException) as error:
        await _discard_session(db, run_session)
        state = getattr(error, "state", None)  # a typed run refusal keeps its state and reason
        raise _StepFailedError(_refusal_text(error), state=state,
                               reason=getattr(error, "code", None) if state else None) from error
    progress.update(run_id=run.id, session_id=run_session.id, href=f"/chat?session_id={run_session.id}")
    await db.commit()


async def _discard_session(db: AsyncSession, run_session: AgentSession) -> None:
    """The refused start's chat session goes; a run that exists after all keeps it."""
    from sqlalchemy import select

    from ...models import WorkflowRunSession

    bound = (await db.execute(select(WorkflowRunSession.id).where(
        WorkflowRunSession.session_id == run_session.id).limit(1))).first()
    if bound is None:
        await db.delete(run_session)
        await db.flush()


class _StepFailedError(Exception):
    """A step refused: the start stops there, keeps what exists and says why (typed: ``state`` and ``reason``)."""

    def __init__(self, message: str, *, state: str | None = None, reason: str | None = None) -> None:
        super().__init__(message)
        self.state = state
        self.reason = reason


_REFUSAL_KEYS = ("error", "state", "reason")


def _record_start(session: AgentSession, proposal_id: str, run_id: str) -> None:
    metadata = dict(session.metadata_ or {})
    starts = {**dict(metadata.get(STARTS_METADATA_KEY) or {}), proposal_id: run_id}
    metadata[STARTS_METADATA_KEY] = dict(list(starts.items())[-MAX_RECORDED_STARTS:])
    session.metadata_ = metadata


def started_run_of(metadata: Any, proposal_id: str) -> str | None:
    """The run the phased start ``proposal_id`` started in this session, or ``None``."""
    starts = metadata.get(STARTS_METADATA_KEY) if isinstance(metadata, dict) else None
    run_id = starts.get(proposal_id) if isinstance(starts, dict) else None
    return run_id if isinstance(run_id, str) and run_id else None


def _jira_line(start: dict[str, Any], jira: dict[str, Any] | None) -> str:
    if not jira or not start.get("jira"):
        return ""
    scope = start["jira"]
    if jira.get("key"):
        return f"Created Jira {scope['issue_type']} {jira['key']} in {scope['project_key']}. "
    return (f"Jira {scope['project_key']}: the {scope['issue_type']} could not be created ({jira['error']}); the Work "
            "item exists on the platform only. ")


_RETRY_HINT = "Press Start again to retry."


def _retry_hint(error: str) -> str:
    """``started.error`` says how to retry, the same words as the assistant message.

    A stored error without the hint gets it once, never twice.
    """
    error = error.strip()
    return error if error.endswith(_RETRY_HINT) else f"{error} {_RETRY_HINT}"


def _started_message(start: dict[str, Any], started: dict[str, Any]) -> str:
    jira = _jira_line(start, started.get("jira"))
    if "error" in started:
        error = str(started["error"]) if started.get("state") else _retry_hint(str(started["error"]))
        return f"{jira}{start['workflow_title']} did not start: {error}"
    item = start["work_item"]
    return (f"{jira}Started {start['workflow_title']} for {item['type_label']} {started['work_item_key']} "
            f"'{item['title']}'. Follow the run: [{start['workflow_title']} run]({started['href']})")


async def _post(db: AsyncSession, session: AgentSession, content: str | None,
                completion_reason: str = "workflow_start_answered") -> None:
    """End the held turn; with ``content`` also the assistant message that names what happened. A typed refusal
    ends it with its reason (``workspace_required``)."""
    from ..session.run_state import RUN_STATUS_COMPLETED, set_session_run_state
    from ..session.stream import session_stream_manager
    from ..session.turn_approval_state import end_chat_turn

    if content:
        db.add(Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content=content,
                       model="workflow-start"))
    metadata = dict(session.metadata_ or {})
    end_chat_turn(metadata)
    session.metadata_ = metadata
    set_session_run_state(session, RUN_STATUS_COMPLETED, completion_reason)
    await db.commit()
    if content:
        await session_stream_manager.publish(session.id, "agent_message",
                                             {"role": "assistant", "content": content, "model": "workflow-start"})


async def _run_start(db: AsyncSession, *, session_id: str, owner_id: str, proposal_id: str, start: dict[str, Any],
                     approval_id: str | None, previous: dict[str, Any] | None) -> None:
    """Jira issue → Work item → run, each kept as it exists; then the chat message naming the outcome."""
    from .phased_start_repository import missing_text

    progress = {key: value for key, value in dict(previous or {}).items() if key not in _REFUSAL_KEYS}
    user = await db.get(User, owner_id)
    try:
        if not _text(start.get("project_id")):  # a run needs a Workspace: nothing is created
            from ..run_admission.denials import MESSAGES, STATE_NEEDS_CONFIGURATION, WORKSPACE_REQUIRED

            raise _StepFailedError(MESSAGES[WORKSPACE_REQUIRED], state=STATE_NEEDS_CONFIGURATION,
                                   reason=WORKSPACE_REQUIRED)
        missing = missing_text(start.get("repository"))
        if missing:  # a run without its repository would stop at its first step: nothing is created
            raise _StepFailedError(missing)
        await _jira_step(db, session_id, owner_id, start, progress, approval_id)
        item = await _item_step(db, session_id, user, start, progress)
        await _budget_step(db, user, start, item)
        await _run_step(db, user, start, item, progress)
    except _StepFailedError as failed:
        # A typed refusal says what to configure; any other refusal is tried again by the next Start.
        progress["error"] = str(failed) if failed.state else _retry_hint(str(failed))
        if failed.state:
            progress.update(state=failed.state, reason=failed.reason)
    session = await _keep(db, session_id, progress)
    if "run_id" in progress:
        _record_start(session, proposal_id, progress["run_id"])
    logger.info("workflow_start.answered", extra={"session_id": session_id, "proposal_id": proposal_id,
                                                  "outcome": "error" if "error" in progress else "started"})
    await _post(db, session, _started_message(start, progress),
                **({"completion_reason": progress["reason"]} if progress.get("state") else {}))


async def answer_phased_start(db: AsyncSession, *, session: AgentSession, owner_id: str, proposal_id: str,
                              approved: bool, message: str = "", approval_id: str | None = None,
                              user_message_id: str = "") -> bool:
    """Answer the session's pending phased start once; ``False`` when the pending proposal is no phased start."""
    from .proposal_decision import DECISIONS_METADATA_KEY, MAX_RECORDED_DECISIONS, pending_workflow_proposal

    pending = pending_workflow_proposal(session.metadata_)
    if pending is None or not pending.get("phased") or pending.get("proposal_id") != proposal_id:
        return False
    metadata = dict(session.metadata_ or {})
    decisions = dict(metadata.get(DECISIONS_METADATA_KEY) or {})
    if proposal_id in decisions:
        return True  # answered once: a repeated resume starts nothing
    decisions[proposal_id] = DECISION_APPLY if approved else DECISION_SKIP
    metadata[DECISIONS_METADATA_KEY] = dict(list(decisions.items())[-MAX_RECORDED_DECISIONS:])
    session.metadata_ = metadata
    if not approved:
        await _post(db, session, None)  # Deny: nothing starts, nothing is sent again
        return True
    start = pending.get("start") if isinstance(pending.get("start"), dict) else await build_start_draft(
        db, session=session, workflow_key=_text(pending.get("workflow_key")), message=message)
    update_proposal(session, start=start, **{HELD_MESSAGE_FIELD: user_message_id})
    await db.commit()  # the answer is recorded before anything starts: a repeated resume finds it
    await _run_start(db, session_id=session.id, owner_id=owner_id, proposal_id=proposal_id, start=start,
                     approval_id=approval_id, previous=None)
    return True


async def retry_phased_start(db: AsyncSession, *, session: AgentSession, owner_id: str, proposal_id: str) -> bool:
    """Start again a phased start whose run did not start (``started.error``); ``False`` for anything else."""
    from .proposal_decision import pending_workflow_proposal

    pending = pending_workflow_proposal(session.metadata_)
    if pending is None or not pending.get("phased") or pending.get("proposal_id") != proposal_id:
        return False
    started = pending.get("started")
    if not isinstance(started, dict) or "error" not in started or not isinstance(pending.get("start"), dict):
        return False
    await _run_start(db, session_id=session.id, owner_id=owner_id, proposal_id=proposal_id, start=pending["start"],
                     approval_id=None, previous=started)
    return True


__all__ = ["STARTS_METADATA_KEY", "answer_phased_start", "retry_phased_start", "started_run_of"]
