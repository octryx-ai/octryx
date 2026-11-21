"""Deciding a waiting human-in-the-loop node.

- **User conversation**: entering the node opens a clarification question in the run's session, so it is listed
  in the requester's Inbox and the next message in the thread answers it (``clarification_service``); the run
  records the reply and continues (``hitl.record_reply``).
- **User confirmation**: a typed payload per subject (``test_contract``, ``ticket_draft``, ``reproduction``,
  ``retry_choice``, ``advance``) with fixed actions *confirm* / *change* / *stop*. The decision stores the hash of
  the payload it decided on; a confirm for another hash (the payload changed) is refused, so a changed payload
  always needs a new confirmation. The payload is rebuilt from current data at decision time: when it changed
  while the run waited (a new plan version, new change units), the waiting payload is refreshed and confirm
  answers ``payload_changed``. The payloads are built from recorded artefacts (``confirmation_payloads``). The
  **test contract** is the change plan the run drafted from its phase's submitted contract: confirm is its
  ``approve`` decision through the change-plan service under the same checks as its route (work operator role,
  the item's Workspace scope), so the acceptance-coverage gate (every criterion maps to an enforceable command,
  or the confirmer takes it over explicitly) decides; the payload's manual-only criteria are taken over by the
  confirm itself (they are in its hash); change is its ``request_clarification``. The decision's hash covers the
  criteria the confirmer took over (``human_verified_criteria``).
- **Approval (four-eyes)**: entering the node files a pending approval (a governance review bound to the run);
  an approver decides under the platform approval rule (``governance/four_eyes``; the single-admin rule allows
  self-approval). A decision made elsewhere (the approvals API) reaches the run the same way, and an expired
  approval pauses the run (``approval_timeout``).

- **Publish & prove** (``documentation/acceptance``): statement (a) ``functional_acceptance`` is
  accepted / not testable yet / rejected (with a reason), on its card or later while the run waits
  (``functional_acceptance``); statement (b) ``publication`` binds the reserved write intent on confirm; the
  ``followup`` card authorises (or changes the summary of) the exact follow-up issue; the ``exception`` card closes a
  declared missing-proof pause. The requester checks a waiting audience receipt or asks for a new one.

Authored node policies select the human decider; confirmations without one go to the requester and the run's
responsible person (``responsible``), as does a run's tool approval. Approvals retain the existing
admin and four-eyes checks, in addition to authored policy.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, User, WorkflowRun
from ...time_utils import utc_now
from .confirmation_steps import (
    _after_s1_confirmation,
    _bind_confirmed_tests,
    _current_payload,
    _decide_s1,
    _decide_test_contract,
    _decide_watched,
)
from .graph import APPROVED, CHANGED, CONFIRMED, REJECTED, STOPPED, SUBJECT_DECISIONS, SUBJECT_FUNCTIONAL_ACCEPTANCE
from .hitl_actions import (
    _ANSWER_INPUTS,
    _APPROVAL_ACTIONS,
    _BLOCKER_SUBJECTS,
    _CONFIRM_ACTIONS,
    _TOOL_APPROVAL_ACTIONS,
    _audit_decision,
    _may_allow_tool,
    _viewer_may_approve,
    _waiting,
    authored_decider,
    reply_payload,
)
from .limits import pause_run
from .pause import payload_hash, record_decision, record_stop, stop_reason
from .po_answers import _ACCEPTED_PROPOSAL_SUBJECTS, _note_po_answer, _record_po_answer, accepted_proposals_answer
from .records import WorkflowRunError, lock_run
from .states import (
    PAUSE_APPROVAL_TIMEOUT,
    STATUS_WAITING,
    WAITING_APPROVAL,
    WAITING_CONFIRMATION,
    WAITING_REPLY,
    WAITING_TOOL_APPROVAL,
)


async def decide(db: AsyncSession, run: WorkflowRun, *, user: User, action: str, body: dict[str, Any]) -> bool:
    """Apply a confirmation or approval action; ``False`` when ``action`` is none of them."""
    waiting = _waiting(run)
    if action == "reply":
        await _decide_reply(db, run, user, body)
        return True
    if await _decide_s1(db, run, user=user, action=action, body=body):
        return True
    if action in _CONFIRM_ACTIONS:
        if run.status != STATUS_WAITING or run.waiting_kind != WAITING_CONFIRMATION:
            raise WorkflowRunError("not_awaiting_confirmation", "The run does not wait for a confirmation.")
        return await _decide_confirmation(db, run, user, _CONFIRM_ACTIONS[action], body)
    if action in _TOOL_APPROVAL_ACTIONS:
        if run.status != STATUS_WAITING or run.waiting_kind != WAITING_TOOL_APPROVAL:
            raise WorkflowRunError("not_awaiting_tool_approval", "The run does not wait for a tool approval.")
        if not await _may_allow_tool(db, run, user):
            raise WorkflowRunError("not_requester", "Only the run's requester or its responsible person allows its "
                                                    "steps.", 403)
        from ..approval.resolution_service import decide_pending_approval

        decided = await decide_pending_approval(
            db, approval_id=str(waiting.get("approval_id") or ""), resolved_by=user.id,
            status=_TOOL_APPROVAL_ACTIONS[action], reason="Decided in the workflow run card.")
        if decided is None:
            raise WorkflowRunError("approval_not_pending", "The approval was already decided.")
        return True
    if action in _APPROVAL_ACTIONS:
        await _decide_approval(db, run, user, action, body, waiting)
        return True
    return False


async def _decide_reply(db: AsyncSession, run: WorkflowRun, user: User, body: dict[str, Any]) -> None:
    """The answer to a waiting user conversation."""
    if run.status != STATUS_WAITING or run.waiting_kind != WAITING_REPLY:
        raise WorkflowRunError("not_awaiting_reply", "The run does not wait for a reply.", 409)
    from .decider import require_node_decider
    from .hitl import MAX_REPLY_CHARS, record_reply

    await require_node_decider(db, run, user)
    if str(body.get("payload_hash") or "") != payload_hash(reply_payload(run)):
        raise WorkflowRunError("payload_changed", "The question changed; review it and answer again.", 409)
    reply = body.get("reply")
    if not isinstance(reply, str) or not reply.strip() or len(reply) > MAX_REPLY_CHARS:
        raise WorkflowRunError("invalid_reply", "Supply a non-empty reply.", 422)
    await record_reply(db, run, reply, user=user)


async def _decide_confirmation(db: AsyncSession, run: WorkflowRun, user: User, value: str,
                               body: dict[str, Any]) -> bool:
    """A confirm / change / stop on a waiting confirmation, decided on the payload as it is now."""
    from .decider import require_node_decider
    from .engine import resolve_current_node

    resolution = await require_node_decider(db, run, user)
    waiting = _waiting(run)
    if waiting.get("subject") == SUBJECT_FUNCTIONAL_ACCEPTANCE:
        raise WorkflowRunError("acceptance_actions", "The functional acceptance is accepted, not testable yet or "
                                                     "rejected.", 422)
    reason = stop_reason(body.get("reason")) if value == STOPPED else ""
    answer = str(body.get("reason") or "").strip()
    if value == CHANGED and waiting.get("subject") in _ANSWER_INPUTS and not answer:
        raise WorkflowRunError("answer_required", "Write the answers the agent should work with.", 422)
    if waiting.get("watched"):
        return await _decide_watched(db, run, user, value, waiting, body)
    payload = await _current_payload(db, run, waiting, refuse_change=value == CONFIRMED, principal=user)
    if value == CONFIRMED:
        await _check_confirmable(db, run, user, waiting, payload, body)
    if payload.get("subject") == "test_contract" and value in (CONFIRMED, CHANGED):
        await _decide_test_contract(db, run, user, value, payload, body)
    decided = dict(payload)
    if value == CONFIRMED and isinstance(body.get("human_verified_criteria"), list):
        decided["human_verified_criteria"] = [str(item) for item in body["human_verified_criteria"]]
    if value == STOPPED:
        decided["stop_reason"] = reason
        record_stop(run, reason=reason, user_id=user.id, via=f"confirmation:{payload.get('subject') or ''}")
    decision = record_decision(db, run, kind="confirmation", subject=str(payload.get("subject") or ""),
                               action=value, payload=decided, user_id=user.id)
    if value == CONFIRMED:
        await _bind_confirmed_tests(db, run, payload)
    await _after_s1_confirmation(db, run, decision, payload, value, body)
    await _confirmation_answers(db, run, user, value, payload, answer)
    await _audit_decision(db, run, user, resolution, decision)
    await resolve_current_node(db, run, value, actor_id=user.id)
    return True


async def _check_confirmable(db: AsyncSession, run: WorkflowRun, user: User, waiting: dict[str, Any],
                             payload: dict[str, Any], body: dict[str, Any]) -> None:
    """A confirm must name the payload's current hash and find nothing missing (an approved spec is frozen)."""
    if str(body.get("payload_hash") or "") != str(waiting.get("payload_hash") or ""):
        raise WorkflowRunError("payload_changed", "What you confirm changed; review it again and confirm.")
    if payload.get("missing") or payload.get("blockers"):
        blockers = [str(item) for item in payload.get("blockers") or []]
        raise WorkflowRunError("nothing_to_confirm", str(payload.get("missing") or (
            blockers[0] if blockers and payload.get("subject") in _BLOCKER_SUBJECTS else
            "The test contract does not cover every acceptance criterion with an enforceable command yet.")), 409)
    if payload.get("subject") == SUBJECT_DECISIONS:
        from .spec_studio.hooks import on_decisions_confirmed

        # Spec Studio: approving the spec freezes it and writes the decisions into SPEC.md.
        await on_decisions_confirmed(db, run, user)


async def _confirmation_answers(db: AsyncSession, run: WorkflowRun, user: User, value: str, payload: dict[str, Any],
                                answer: str) -> None:
    """The product owner's answers a confirmation carries: a change request, typed answers or accepted proposals."""
    if value == CHANGED and answer and payload.get("subject") not in _ANSWER_INPUTS:
        from .corrections import change_request

        await change_request(db, run, answer, user, str(payload.get("subject") or ""))
    if value == CHANGED and payload.get("subject") in _ANSWER_INPUTS:
        _record_po_answer(run, answer, user_id=user.id)
        await _note_po_answer(db, run, answer, user, str(payload.get("subject") or ""))
    elif value == CONFIRMED and payload.get("subject") in _ACCEPTED_PROPOSAL_SUBJECTS:
        # Without a recorded answer for "accept all proposals" the draft phase is told there are no
        # product_owner_answers and drops or reverses the accepted proposals.
        # Accepting the proposals is an answer: the proposals themselves, as the product owner accepted them.
        accepted = accepted_proposals_answer(str(payload.get("text") or ""))
        if accepted:
            _record_po_answer(run, accepted, user_id=user.id)
            await _note_po_answer(db, run, accepted, user, str(payload.get("subject") or ""))


async def _decide_approval(db: AsyncSession, run: WorkflowRun, user: User, action: str, body: dict[str, Any],
                           waiting: dict[str, Any]) -> None:
    """Approve or reject a waiting four-eyes approval under the approval rule."""
    if run.status != STATUS_WAITING or run.waiting_kind != WAITING_APPROVAL:
        raise WorkflowRunError("not_awaiting_approval", "The run does not wait for an approval.")
    if await authored_decider(db, run):
        from .decider import require_node_decider

        await require_node_decider(db, run, user)
        waiting = _waiting(run)
    if not await _viewer_may_approve(db, run, user):
        raise WorkflowRunError("four_eyes", "Another admin approves this step (approval rule: four-eyes).", 403)
    from ..approval.resolution_service import decide_pending_approval

    approval_id = str(waiting.get("approval_id") or "")
    decided = await decide_pending_approval(db, approval_id=approval_id, resolved_by=user.id,
                                            status=_APPROVAL_ACTIONS[action],
                                            reason=str(body.get("reason") or "")[:500] or None)
    if decided is None:
        raise WorkflowRunError("approval_not_pending", "The approval was already decided.")
    await approval_decided(db, decided, run=run)


async def approval_decided(db: AsyncSession, approval: Approval, *, run: WorkflowRun | None = None) -> None:
    """A decided run approval moves its run: approved / rejected route on; expired pauses it."""
    from .engine import resolve_current_node

    if run is None:
        run = (await db.execute(select(WorkflowRun).where(
            WorkflowRun.status.in_((STATUS_WAITING,)), WorkflowRun.waiting_kind == WAITING_APPROVAL,
        ))).scalars().all()
        run = next((item for item in run if _waiting(item).get("approval_id") == approval.id), None)
    if run is None:
        return
    run = await lock_run(db, run)
    if _waiting(run).get("approval_id") != approval.id or run.waiting_kind != WAITING_APPROVAL:
        return
    if approval.status == "expired":
        await pause_run(db, run, reason=PAUSE_APPROVAL_TIMEOUT, actor_id=None, detail={
            "message": "the approval was not decided in time",
            "resume": {"kind": "approval"},
        })
        return
    resolution = None
    actor = await db.get(User, approval.approved_by) if approval.approved_by else None
    if await authored_decider(db, run):
        from .decider import require_node_decider

        if actor is None:
            raise WorkflowRunError("not_decider", "A current human decider must decide this approval.", 403)
        resolution = await require_node_decider(db, run, actor)
        if not await _viewer_may_approve(db, run, actor):
            raise WorkflowRunError("four_eyes", "The node decider must also satisfy the approval rule.", 403)
    value = APPROVED if approval.status == "approved" else REJECTED
    if value == APPROVED:
        from .deploy_four_eyes import record_approval

        record_approval(run, approval_id=approval.id, approved_by=approval.approved_by, node_id=run.current_node_id)
    decision = record_decision(db, run, kind="approval", subject=run.current_node_id or "", action=value,
                    payload={"approval_id": approval.id, "decided_at": utc_now().isoformat()},
                    user_id=approval.approved_by, approval_id=approval.id)
    if resolution is not None:
        await _audit_decision(db, run, actor, resolution, decision)
    await resolve_current_node(db, run, value, actor_id=approval.approved_by)


__all__ = ["approval_decided", "decide"]
