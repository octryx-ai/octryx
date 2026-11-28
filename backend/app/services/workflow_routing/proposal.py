"""Workflow proposals: the platform proposes a published phased workflow, the user confirms."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..content_security.refusal import ContentPolicyRefusedError
from ..policy_lists.workflow_proposal_settings import read_workflow_proposal_settings
from ..prompt_catalog import bound_prompt_set, prompt_set_scope, resolve_prompt_set
from .explicit_selection import explicit_mode_no_selection_resolution, resolve_explicit_workflow_selection
from .proposal_contract import (
    ProposalAnswer,
    build_proposal_catalog,
    build_proposal_prompt,
    split_instruction,
    validate_proposal_answer,
)
from .proposal_model import ProposalModelUnavailableError, governed_proposal_model
from .proposal_policy import workflow_proposals_enabled
from .proposal_states import (
    PROPOSAL_REASON_CODES,
    STATUS_DISABLED,
    STATUS_NEEDS_CONFIRMATION,
    STATUS_NONE,
    STATUS_OFFERED,
    WORKFLOW_PROPOSAL_KEY,
    WORKFLOW_PROPOSAL_SOURCE,
    WORKFLOW_PROPOSAL_VERSION,
)

logger = logging.getLogger(__name__)

# A workflow that only builds what an existing item already holds -> the workflow that first creates it.
# "Create an Epic in Jira, have the specification written, split it into 2 stories and build them" must not be
# proposed epic-delivery, which builds only an epic's existing stories;
# the idea needs spec-writing, whose epic chain then starts epic-delivery itself.
_BUILDS_EXISTING_ITEM = {"epic-delivery": "spec-writing"}
# A work item key: the structural sign that the instruction refers to an existing item.
_ITEM_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


def _without_missing_item(answer: ProposalAnswer, message: str, catalog_keys: set[str]) -> ProposalAnswer:
    successor = _BUILDS_EXISTING_ITEM.get(str(answer.workflow_key or ""))
    if successor is None or successor not in catalog_keys:
        return answer
    instruction, _quoted = split_instruction(message)
    if _ITEM_KEY.search(instruction):
        return answer
    reason = f"No existing item is named, so {successor} creates it first and then starts {answer.workflow_key}."
    return dataclasses.replace(answer, workflow_key=successor, reason=reason)


def _record(status: str, reason_code: str, **fields: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "version": WORKFLOW_PROPOSAL_VERSION,
        "status": status,
        "reason_code": reason_code if reason_code in PROPOSAL_REASON_CODES else "proposal_failed",
        "proposal_id": None,
        "workflow_key": None,
        "workflow_title": None,
        "confidence": None,
        "reason": None,
        "change_capable": None,
        "dispatch": None,
        # A phased workflow starts as a workflow run for a Work item (``phased_start``): the start draft the card
        # shows and, after the confirmation, what was started.
        "phased": None,
        "start": None,
        "started": None,
    }
    record.update({key: value for key, value in fields.items() if key in record})
    return record


def _no_workflow(record: dict[str, Any]) -> dict[str, Any]:
    return {**explicit_mode_no_selection_resolution(), WORKFLOW_PROPOSAL_KEY: record}


def _needs_confirmation(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **explicit_mode_no_selection_resolution(),
        "source": WORKFLOW_PROPOSAL_SOURCE,
        "status": STATUS_NEEDS_CONFIRMATION,
        "unmatched_reason": ("A workflow was proposed that needs the user's confirmation before it can run."),
        WORKFLOW_PROPOSAL_KEY: record,
    }


def _held_or_offered(requested: bool, record: dict[str, Any]) -> dict[str, Any]:
    if requested:
        return _needs_confirmation(record)
    return _no_workflow({**record, "status": STATUS_OFFERED, "reason_code": "offered_not_requested"})


def explicit_phased_selection_resolution(workflow_key: str, workflow_title: str | None) -> dict[str, Any]:
    return _needs_confirmation(_record(
        STATUS_NEEDS_CONFIRMATION, "explicit_phased_selection", phased=True, change_capable=True,
        proposal_id=uuid.uuid4().hex, workflow_key=workflow_key, workflow_title=workflow_title or workflow_key,
        reason="Chosen in the composer."))


def user_selected_no_workflow_resolution() -> dict[str, Any]:
    return _no_workflow(_record(STATUS_NONE, "user_selected_no_workflow"))


def _unavailable_reason(error: ProposalModelUnavailableError) -> str:
    if error.reason == "no_runtime_configured":
        return "no_runtime_configured"
    if error.reason == "model_unavailable":
        return "model_unavailable"
    return "admission_needs_configuration" if error.state == "needs_configuration" else "admission_denied"


# English greetings, thanks and sign-offs; a message in another language goes to the router, which reads any language.
# A confirmation ("yes") is not here: it may answer a question.
_SMALL_TALK = frozenset("""
hi hello hey morning evening good thanks thank thx ty you many much very
super perfect great cool top nice a lot lots so
bye cheers
""".split())
_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)


def conversational_message(message: str) -> bool:
    words = _WORDS.findall(str(message or "").casefold())
    return bool(words) and len(words) <= 6 and all(word in _SMALL_TALK for word in words)


async def _propose(db: AsyncSession, *, user_message: str, project_id: str | None) -> dict[str, Any]:
    if not await workflow_proposals_enabled(db, project_id):
        return _no_workflow(_record(STATUS_DISABLED, "policy_disabled"))
    settings = await read_workflow_proposal_settings(db)
    message = str(user_message or "").strip()
    if not message:
        return _no_workflow(_record(STATUS_NONE, "empty_message"))
    if conversational_message(message):
        return _no_workflow(_record(STATUS_NONE, "conversational_message"))
    catalog = await build_proposal_catalog(db, project_id=project_id)
    if not catalog:
        return _no_workflow(_record(STATUS_NONE, "no_published_definitions"))
    try:
        model = await governed_proposal_model(db, project_id=project_id)
    except ProposalModelUnavailableError as error:
        return _no_workflow(_record(STATUS_NONE, _unavailable_reason(error)))
    # In a turn the turn's prompt set is bound; the pre-turn prefetch resolves the Workspace's own.
    prompt_set = bound_prompt_set() or await resolve_prompt_set(db, workspace_id=project_id)
    with prompt_set_scope(prompt_set):
        system, user = build_proposal_prompt(catalog, message)
    try:
        reply = await asyncio.wait_for(model.answer(system=system, user=user), timeout=settings.timeout_seconds)
    except TimeoutError:
        return _no_workflow(_record(STATUS_NONE, "timeout", dispatch=model.usage.to_dict()))
    except ProposalModelUnavailableError as error:
        return _no_workflow(_record(STATUS_NONE, _unavailable_reason(error), dispatch=model.usage.to_dict()))
    except ContentPolicyRefusedError:
        # A platform content policy refused the message at the model call (content_security.model_call).
        return _no_workflow(_record(STATUS_NONE, "content_blocked", dispatch=model.usage.to_dict()))
    dispatch = model.usage.to_dict()
    if reply.answer is None:
        return _no_workflow(_record(STATUS_NONE, "model_refused", dispatch=dispatch))
    catalog_keys = {entry["workflow_key"] for entry in catalog}
    answer = validate_proposal_answer(reply.answer, catalog_keys)
    if answer.outcome is not None:
        return _no_workflow(
            _record(STATUS_NONE, answer.outcome, confidence=answer.confidence, reason=answer.reason, dispatch=dispatch)
        )
    answer = _without_missing_item(answer, message, catalog_keys)
    title = next((entry["name"] for entry in catalog if entry["workflow_key"] == answer.workflow_key), None)
    common = {
        "workflow_key": answer.workflow_key,
        "workflow_title": title,
        "confidence": answer.confidence,
        "reason": answer.reason,
        "dispatch": dispatch,
    }
    if answer.confidence == "low":
        return _no_workflow(_record(STATUS_NONE, "low_confidence", **common))
    resolution = await resolve_explicit_workflow_selection(
        db, workflow_key=str(answer.workflow_key), project_id=project_id
    )
    if resolution.get("status") != "workflow_run_required":
        return _no_workflow(_record(STATUS_NONE, "unknown_key", **common))
    # A phased workflow is only ever proposed; the user starts it as a run for a Work item.
    return _held_or_offered(
        answer.requested,
        _record(
            STATUS_NEEDS_CONFIRMATION,
            "workflow_run_required",
            phased=True,
            change_capable=True,
            proposal_id=uuid.uuid4().hex,
            **common,
        ),
    )


async def resolve_workflow_proposal_for_turn(
    db: AsyncSession,
    *,
    user_message: str,
    project_id: str | None,
) -> dict[str, Any]:
    try:
        return await _propose(db, user_message=user_message, project_id=project_id)
    except Exception:  # noqa: BLE001 - recorded as the explicit ``proposal_failed`` outcome; no text is kept
        logger.warning("workflow_proposal failed")
        return _no_workflow(_record(STATUS_NONE, "proposal_failed"))


def workflow_proposal_of(resolution: Any) -> dict[str, Any] | None:
    record = resolution.get(WORKFLOW_PROPOSAL_KEY) if isinstance(resolution, dict) else None
    return record if isinstance(record, dict) and record.get("version") == WORKFLOW_PROPOSAL_VERSION else None


__all__ = [
    "explicit_phased_selection_resolution",
    "resolve_workflow_proposal_for_turn",
    "user_selected_no_workflow_resolution",
    "workflow_proposal_of",
]
