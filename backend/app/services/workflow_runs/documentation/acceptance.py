"""Publish & prove: statement (a), its pending state, the follow-up intent, the exception, ``done``.

**Two independent statements.** After the merge the PM stage shows two sequential cards, each with its own payload,
hash and ``WorkflowRunDecision``; neither implies the other:

- (a) ``functional_acceptance``: the server's statement that the merged change was observed to meet the acceptance
  criteria on a **named** environment and an **observed** build (the tested commit and its CI result, never a
  claim that a pre-merge CI build ran on the merge commit). Actions: accept (environment and build required), not
  testable yet, reject (with a reason).
- (b) ``publication`` (:func:`publication_payload`): this page, body and target, with the marker the reserved write
  intent carries, to the named audience. When (a) is still pending the body itself says "functional acceptance pending
  as of <time>" and links the run.

**Immutable AS-OF semantics.** A page published while (a) is pending is a dated fact about that page version. A
later (a) is a separate, dated decision shown next to it; the page is never edited silently, and refreshing it needs
a new (b) → compare-and-set → sync → proof cycle (a new publication of this run or a new run).

**Pending.** ``acceptance_open`` waits (``functional_acceptance``: owner the requester, Inbox, 24 h reminder, pause
``acceptance_timeout`` after 72 h) until (a) is recorded or rejected. A **late rejection** follows exactly the path of
an initial one: the authorised follow-up intent (card ``followup``) → create → read back → ``blocked``; there is no
direct-blocked shortcut and no revert.

**Exception** (subject ``exception``): only from the declared missing-proof pauses (``audience_unproven``,
``documentation_missing``, ``acceptance_timeout``): the requester sees the exact follow-up intent, authorises it, the
platform creates and reads it back, then the requester confirms the exception bound to {reason, missing proof, owner,
follow-up key}; only then ``done_with_exception``.

**Done** (:func:`done_check`) requires a resolved (a) **and** a valid, currently bound publication proof: the newest
write intent of the run sent and confirmed for the published page/version, Knowledge at that version, and the
audience receipt (positive) and the outsider receipt (negative) consumed for it.

There is no ``handed_over`` offer or outcome on this path (no cross-owner handoff).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun, WorkflowRunDecision
from ....time_utils import ensure_utc, utc_now
from ..graph import ACCEPTED, NOT_TESTABLE_YET, REJECTED, SUBJECT_FUNCTIONAL_ACCEPTANCE
from ..platform.dispatch import CLASS_INVALID, FAILED, SUCCEEDED, ToolOutcome
from ..records import WorkflowRunError, record_event
from ..states import (
    PAUSE_ACCEPTANCE_TIMEOUT,
    PAUSE_AUDIENCE_UNPROVEN,
    PAUSE_DOCUMENTATION_MISSING,
    STATUS_WAITING,
    WAITING_CONFIRMATION,
    WAITING_FUNCTIONAL_ACCEPTANCE,
)
from .s1_graph import ACCEPTANCE_OPEN, facts, set_facts

STATE_OPEN, STATE_PENDING = "open", "pending"
PURPOSE_REJECTION, PURPOSE_EXCEPTION = "rejection", "exception"
FOLLOWUP_ISSUE_TYPE = "Task"
FINAL_STATUS = "final"
MAX_DIFF_LINES = 200
ACTION_ACCEPT, ACTION_NOT_TESTABLE, ACTION_REJECT = "accept", "not_testable_yet", "reject_acceptance"
ACTION_TAKE_EXCEPTION = "take_exception"
ACCEPTANCE_ACTIONS = {ACTION_ACCEPT: ACCEPTED, ACTION_NOT_TESTABLE: NOT_TESTABLE_YET, ACTION_REJECT: REJECTED}
_MISSING_PROOF = {
    PAUSE_AUDIENCE_UNPROVEN: "the audience principal's retrieval proof of the published page",
    PAUSE_DOCUMENTATION_MISSING: "the feature documentation of the merged change",
    PAUSE_ACCEPTANCE_TIMEOUT: "the functional acceptance (a) on the named environment",
}


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat().replace("+00:00", "Z") if value is not None else None


# --- Statement (a) ---------------------------------------------------------------------------------------------

def acceptance_state(run: WorkflowRun) -> dict[str, Any]:
    """The newest (a) of this run: ``open`` (none), ``accepted``, ``pending`` (not testable yet, with ``as_of``),
    ``rejected``."""
    latest = dict(facts(run).get("acceptance") or {})
    if not latest:
        return {"state": STATE_OPEN}
    value = str(latest.get("decision") or "")
    state = STATE_PENDING if value == NOT_TESTABLE_YET else value
    return {"state": state, "decision_id": latest.get("decision_id"), "as_of": latest.get("at"),
            "late": bool(latest.get("late"))}


def _build(run: WorkflowRun) -> tuple[dict[str, Any], list[str]]:
    """The **observed** build: the tested (pushed) commit and its CI result as the run recorded them."""
    context = dict(run.context or {})
    ci = dict(context.get("ci") or {})
    pushed = str(context.get("head_sha") or "")
    tested = str(ci.get("sha") or "")
    url = str(ci.get("url") or "")
    build = {"tested_sha": tested, "pushed_sha": pushed, "ci_provider": str(ci.get("provider") or ""),
             "ci_state": str(ci.get("state") or ""), "ci_url": url if url.lower().startswith(("https://", "http://"))
             else "", "ci_build": str(ci.get("build") or ""),
             # Never a claim that the pre-merge CI build ran on the merge commit.
             "note": "CI ran on the pushed commit before the merge; it is not a build of the merge commit."}
    blockers = []
    if not tested:
        blockers.append("no tested commit was observed by this run")
    if tested and pushed and tested != pushed:
        blockers.append("CI evidence is not bound to the pushed commit")
    if build["ci_state"] != "succeeded":
        blockers.append("CI did not succeed on the tested commit")
    return build, blockers


async def confirmed_criteria(db: AsyncSession, run: WorkflowRun) -> list[dict[str, Any]]:
    """Only the newest human-confirmed test contract supplies the criteria; a later draft is not acceptance fact."""
    decision = (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == run.id, WorkflowRunDecision.kind == "confirmation",
        WorkflowRunDecision.subject == "test_contract").order_by(
            WorkflowRunDecision.created_at.desc()).limit(1))).scalar_one_or_none()
    if decision is None or decision.action != "confirmed":
        return []
    return [dict(item) for item in dict(decision.payload or {}).get("acceptance_criteria") or []
            if isinstance(item, dict)]


async def acceptance_payload(db: AsyncSession, run: WorkflowRun, *, late: bool = False) -> dict[str, Any]:
    from ...project.service import get_project_config
    from .preflight import acceptance_environment

    environment = acceptance_environment(await get_project_config(run.project_id, db))
    build, blockers = _build(run)
    criteria = await confirmed_criteria(db, run)
    if not criteria:
        blockers.append("no human-confirmed acceptance criteria are recorded")
    if environment is None:
        blockers.insert(0, "no named acceptance environment is configured (feature_documentation."
                           "acceptance_environment); record 'not testable yet' or reject")
    where = (f"{environment.name} ({environment.kind}{', ' + environment.url if environment.url else ''})"
             if environment else "no named environment")
    payload: dict[str, Any] = {
        "subject": SUBJECT_FUNCTIONAL_ACCEPTANCE,
        "statement": (f"I observed the merged change on {where}, build {build['tested_sha'][:12] or 'unknown'}, and "
                      "it meets the acceptance criteria below."),
        "environment": environment.to_dict() if environment else None, "build": build,
        "acceptance_criteria": criteria, "accept_blockers": blockers,
    }
    if late:
        state, published = acceptance_state(run), dict(facts(run).get("publication") or {})
        payload["pending_since"] = state.get("as_of")
        payload["published"] = {key: published.get(key) for key in (
            "page_id", "version", "acceptance_as_published", "acceptance_as_of", "published_at")}
        payload["refresh_note"] = ("This decision is recorded on the run next to the published version; the page is "
                                   "not edited. A page refresh needs a new publication (b).")
    return payload


def _refresh_waiting(db: AsyncSession, run: WorkflowRun, waiting: dict[str, Any], current: dict[str, Any]) -> None:
    from ..pause import payload_hash

    run.node_state = {**dict(run.node_state or {}), "waiting": {**waiting, "payload": current,
                                                                 "payload_hash": payload_hash(current)}}
    record_event(db, run, "confirmation_payload_refreshed", node_id=run.current_node_id,
                 detail={"subject": SUBJECT_FUNCTIONAL_ACCEPTANCE})


async def decide_acceptance(db: AsyncSession, run: WorkflowRun, *, user: User, action: str,
                            body: dict[str, Any]) -> None:
    """Record (a) on its card or, later, at ``acceptance_open``: a separate, dated decision with its own hash."""
    from ..confirmation_payloads import confirmation_payload
    from ..engine import resolve_current_node
    from ..engine_context import _set_context
    from ..external_step import pass_key
    from ..graph import graph_for_run
    from ..pause import payload_hash, record_decision, stop_reason

    value = ACCEPTANCE_ACTIONS[action]
    waiting = dict(dict(run.node_state or {}).get("waiting") or {})
    at_card = (run.status == STATUS_WAITING and run.waiting_kind == WAITING_CONFIRMATION
               and waiting.get("subject") == SUBJECT_FUNCTIONAL_ACCEPTANCE)
    late = run.status == STATUS_WAITING and run.waiting_kind == WAITING_FUNCTIONAL_ACCEPTANCE
    if not (at_card or late):
        raise WorkflowRunError("not_awaiting_acceptance", "The run does not wait for the functional acceptance.")
    from ..decider import audit_decider_decision, require_node_decider

    decision_node = str(run.current_node_id or "")
    resolution = await require_node_decider(db, run, user)
    if late and value == NOT_TESTABLE_YET:
        raise WorkflowRunError("acceptance_already_pending", "The functional acceptance is pending already.", 422)
    if at_card:
        node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
        current = await confirmation_payload(db, run, node) if node is not None else dict(waiting.get("payload") or {})
    else:
        current = await acceptance_payload(db, run, late=True)
    if payload_hash(current) != waiting.get("payload_hash"):
        _refresh_waiting(db, run, waiting, current)
        raise WorkflowRunError("payload_changed", "What you decide on changed while the run waited; review the current "
                                                  "statement and decide again.", persist=True)
    if str(body.get("payload_hash") or "") != str(waiting.get("payload_hash") or ""):
        raise WorkflowRunError("payload_changed", "What you decide on changed; review it again and decide.")
    if value == ACCEPTED and current.get("accept_blockers"):
        raise WorkflowRunError("nothing_to_confirm", str(current["accept_blockers"][0]), 409)
    reason = stop_reason(body.get("reason")) if value == REJECTED else ""
    decided = {**current, "decision": value, "decided_at": utc_now().isoformat(), "late": late,
               **({"reason": reason} if reason else {})}
    decision = record_decision(db, run, kind="confirmation", subject=SUBJECT_FUNCTIONAL_ACCEPTANCE, action=value,
                               payload=decided, user_id=user.id)
    await db.flush()
    audit_decider_decision(db, run, user, resolution, node_id=decision_node,
                           payload_hash=decision.payload_hash, decision_id=decision.id)
    history = list(facts(run).get("acceptance_history") or [])
    entry = {"decision_id": decision.id, "decision": value, "at": _iso(decision.created_at) or decided["decided_at"],
             "late": late, "payload_hash": decision.payload_hash, **({"reason": reason} if reason else {})}
    set_facts(run, acceptance=entry, acceptance_history=[*history, entry][-20:])
    if value == REJECTED:
        from ..corrections import change_request

        await change_request(db, run, reason, user, SUBJECT_FUNCTIONAL_ACCEPTANCE)
        # The same authorised follow-up path for an initial and a late rejection: never a direct ``blocked``.
        set_facts(run, followup={"purpose": PURPOSE_REJECTION, "reason": reason, "late": late,
                                 "decision_id": decision.id, "owner": run.requested_by, "at": entry["at"]})
    if late:
        _set_context(run, "action_ledger", pass_key(run, run.current_node_id),
                     {"action": ACCEPTANCE_OPEN, "result": value})
    await resolve_current_node(db, run, value, actor_id=user.id)


async def acceptance_open(db: AsyncSession, run: WorkflowRun, node: Any) -> tuple[ToolOutcome, str]:
    """After the proof: (a) accepted routes on, a pending (a) waits for its separate, dated decision."""
    from ..pause import payload_hash
    from ..platform_actions import WAIT

    state = acceptance_state(run)
    if state["state"] == ACCEPTED:
        return ToolOutcome(SUCCEEDED, {"acceptance": state}), ACCEPTED
    if state["state"] == REJECTED:
        return ToolOutcome(SUCCEEDED, {"acceptance": state}), REJECTED
    if state["state"] != STATE_PENDING:
        return ToolOutcome(FAILED, reason="no functional acceptance (a) was recorded in this run",
                           failure_class=CLASS_INVALID), FAILED
    payload = await acceptance_payload(db, run, late=True)
    run.status, run.waiting_kind = STATUS_WAITING, WAITING_FUNCTIONAL_ACCEPTANCE
    run.node_state = {**dict(run.node_state or {}), "waiting": {
        "kind": WAITING_FUNCTIONAL_ACCEPTANCE, "title": node.title, "since": utc_now().isoformat(),
        "subject": SUBJECT_FUNCTIONAL_ACCEPTANCE, "payload": payload, "payload_hash": payload_hash(payload),
        "question": f"Functional acceptance pending since {state.get('as_of')}: record it or reject it."}}
    return ToolOutcome("waiting", {"acceptance": state}), WAIT


__all__ = [
    "ACCEPTANCE_ACTIONS", "ACTION_TAKE_EXCEPTION", "acceptance_open", "acceptance_payload", "acceptance_state",
    "decide_acceptance",
]
