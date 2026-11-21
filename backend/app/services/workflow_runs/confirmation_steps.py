"""The steps around a confirmation: its current payload, the test contract, watched and publish-and-prove cards."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from .confirmation_payloads import (
    confirmation_payload,
    contract_test_ids,
    contract_test_roles,
    reproduction_roles,
    reproduction_tests,
)
from .graph import CHANGED, CONFIRMED, NODE_CONFIRMATION, STOPPED, SUBJECT_FOLLOWUP, SUBJECT_PUBLICATION
from .hitl_actions import ACTION_CHECK_AUDIENCE, ACTION_NEW_AUDIENCE, _audit_decision, _set_waiting, _waiting
from .pause import payload_hash, record_decision
from .records import WorkflowRunError, record_event
from .states import PAUSE_AUDIENCE_UNPROVEN, STATUS_PAUSED


async def _decide_test_contract(db: AsyncSession, run: WorkflowRun, user: User, value: str,
                                payload: dict[str, Any], body: dict[str, Any]) -> None:
    from ..secure_work.access import get_scoped_change_plan, require_work_operator
    from ..secure_work.plans.change_plans import decide_change_plan

    plan_id = str(payload.get("change_plan_id") or "")
    if not plan_id:
        return
    request = {"action": "approve", "reason": "Confirmed as the test contract of a workflow run."}
    if value == CHANGED:
        request = {"action": "request_clarification", "reason": "Changes requested in a workflow run."}
    if value == CONFIRMED:
        # The manual-only criteria the payload showed are taken over by this confirm (attributed in the decision).
        taken_over = [str(item) for item in payload.get("manual_only") or []]
        if isinstance(body.get("human_verified_criteria"), list):
            taken_over += [str(item) for item in body["human_verified_criteria"]]
        if taken_over:
            request["human_verified_criteria"] = list(dict.fromkeys(taken_over))
    try:
        # The guards of ``POST /change-plans/{id}/decision``: a run is no way around them.
        await require_work_operator(db, user)
        await get_scoped_change_plan(db, user, plan_id)
        await decide_change_plan(db, change_plan_id=plan_id, current_user=user, payload=request)
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
        raise WorkflowRunError("test_contract_refused", str(detail.get("message") or detail), error.status_code)


async def _decide_s1(db: AsyncSession, run: WorkflowRun, *, user: User, action: str, body: dict[str, Any]) -> bool:
    """Publish & prove: statement (a), the exception from a declared pause, the audience receipt check."""
    from .documentation import acceptance, followup_exception

    if action in acceptance.ACCEPTANCE_ACTIONS:
        await acceptance.decide_acceptance(db, run, user=user, action=action, body=body)
        return True
    if action == acceptance.ACTION_TAKE_EXCEPTION:
        await followup_exception.take_exception(db, run, user=user)
        return True
    if action not in (ACTION_CHECK_AUDIENCE, ACTION_NEW_AUDIENCE):
        return False
    if user.id != run.requested_by:
        raise WorkflowRunError("not_requester", "Only the run's requester asks for the audience check.", 403)
    if action == ACTION_CHECK_AUDIENCE:
        from .documentation.s1_graph import check_audience_receipt

        result = await check_audience_receipt(db, run, actor_id=user.id)
        if result == "not_waiting":
            raise WorkflowRunError("not_awaiting_audience", "The run does not wait for an audience receipt.")
        if result == "pending":
            raise WorkflowRunError("receipt_not_recorded", "The audience principal has not run the check yet.")
        return True
    if run.status != STATUS_PAUSED or run.pause_reason != PAUSE_AUDIENCE_UNPROVEN:
        raise WorkflowRunError("not_audience_unproven", "The run is not paused for an unproven audience.")
    from .engine import restart_at

    record_decision(db, run, kind="pause", subject=PAUSE_AUDIENCE_UNPROVEN, action=ACTION_NEW_AUDIENCE,
                    payload={"node_id": run.current_node_id}, user_id=user.id)
    await restart_at(db, run, str(run.current_node_id or ""), actor_id=user.id)  # a new pass: a new challenge
    return True


async def _after_s1_confirmation(db: AsyncSession, run: WorkflowRun, decision: Any, payload: dict[str, Any],
                                 value: str, body: dict[str, Any]) -> None:
    """Card (b) binds the reserved intent; the follow-up card authorises or changes the exact issue."""
    subject = payload.get("subject")
    if subject == SUBJECT_PUBLICATION and value == CONFIRMED:
        from .documentation.s1_graph import approve_publication

        await approve_publication(db, run, decision, payload)
    elif subject == SUBJECT_FOLLOWUP and value == CONFIRMED:
        from .documentation.followup_exception import authorise_followup

        await db.flush()
        await authorise_followup(db, run, decision, payload)
    elif subject == SUBJECT_FOLLOWUP and value == CHANGED:
        from .documentation.followup_exception import change_followup

        change_followup(run, body.get("reason"))


async def _current_payload(
    db: AsyncSession, run: WorkflowRun, waiting: dict[str, Any], *, refuse_change: bool, principal=None
) -> dict[str, Any]:
    """The confirmation payload rebuilt from current data; a changed one replaces the waiting one.

    A confirm of a changed payload is refused (``payload_changed``, the refreshed payload is kept so the card
    shows it); change and stop act on the current payload.
    """
    from .graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    if node is None or node.kind != NODE_CONFIRMATION:
        return dict(waiting.get("payload") or {})
    from .specification.integration import KINDS

    if str(node.config.get("shows") or "") in KINDS:
        current = await confirmation_payload(db, run, node, principal=principal,
                                             purpose="confirm" if refuse_change else "preview")
    else:
        current = await confirmation_payload(db, run, node)
    if payload_hash(current) == waiting.get("payload_hash"):
        return current
    _set_waiting(run, {**waiting, "payload": current, "payload_hash": payload_hash(current)})
    record_event(db, run, "confirmation_payload_refreshed", node_id=node.id,
                 detail={"subject": current.get("subject")})
    if refuse_change:
        raise WorkflowRunError("payload_changed", "What you confirm changed while the run waited; review the "
                                                  "current version and confirm again.", persist=True)
    return current


async def _decide_watched(db: AsyncSession, run: WorkflowRun, user: User, value: str, waiting: dict[str, Any],
                          body: dict[str, Any]) -> bool:
    """A watched condition was met: "go on" routes on it, "not now" keeps waiting, "stop" aborts."""
    from .decider import require_node_decider
    from .engine import resolve_current_node
    from .pause import abort_run

    resolution = await require_node_decider(db, run, user)
    waiting = _waiting(run)
    payload = dict(waiting.get("payload") or {})
    if value == CONFIRMED and str(body.get("payload_hash") or "") != str(waiting.get("payload_hash") or ""):
        raise WorkflowRunError("payload_changed", "What you confirm changed; review it again and confirm.")
    decision = record_decision(db, run, kind="confirmation", subject="advance", action=value,
                               payload=payload, user_id=user.id)
    await _audit_decision(db, run, user, resolution, decision)
    if value == CONFIRMED:
        await resolve_current_node(db, run, str(waiting["watched"]), actor_id=user.id)
    elif value == STOPPED:
        await abort_run(db, run, user=user, reason=str(body.get("reason") or ""))
    return True


async def _bind_confirmed_tests(db: AsyncSession, run: WorkflowRun, payload: dict[str, Any]) -> None:
    """What the person confirmed becomes the tests the TDD gates judge, with the content they confirmed."""
    from .test_runs import confirm_tests, snapshot_confirmed_tests

    subject = payload.get("subject")
    if subject == "test_contract":
        confirm_tests(run, contract_test_ids(payload), roles=contract_test_roles(payload))
    elif subject == "reproduction":
        tests, symptom = reproduction_tests(payload)
        confirm_tests(run, tests, symptom=symptom, roles=reproduction_roles(tests))
    else:
        return
    await snapshot_confirmed_tests(db, run)
