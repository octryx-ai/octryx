"""The actions a viewer may take on a waiting human-in-the-loop node, and who may decide it."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, User, WorkflowRun
from ..admin.governance.admin_access_service import is_global_admin
from ..governance.four_eyes import FOUR_EYES_PASSING_STATUSES, decide_four_eyes
from .confirmation_payloads import confirmation_payload
from .graph import (
    APPROVED,
    CHANGED,
    CONFIRMED,
    NODE_APPROVAL,
    NODE_CONFIRMATION,
    NODE_CONVERSATION,
    REJECTED,
    STOPPED,
    SUBJECT_DECISIONS,
    SUBJECT_FOLLOWUP,
    SUBJECT_FUNCTIONAL_ACCEPTANCE,
    SUBJECT_INTERVIEW,
    SUBJECT_PUBLICATION,
    SUBJECT_READINESS,
    PhasedNode,
)
from .pause import payload_hash
from .records import main_session_id
from .states import (
    EXCEPTION_PAUSE_REASONS,
    PAUSE_AUDIENCE_UNPROVEN,
    STATUS_PAUSED,
    STATUS_WAITING,
    WAITING_APPROVAL,
    WAITING_AUDIENCE_RECEIPT,
    WAITING_CONFIRMATION,
    WAITING_FUNCTIONAL_ACCEPTANCE,
    WAITING_REPLY,
    WAITING_TOOL_APPROVAL,
)

APPROVAL_ACTION_PREFIX = "workflow_run.approval"


# Fixed, server-owned labels of the three confirmation actions, per subject.
CONFIRMATION_LABELS: dict[str, dict[str, str]] = {
    "test_contract": {CONFIRMED: "Confirm these tests", CHANGED: "Change the tests", STOPPED: "Stop"},
    "ticket_draft": {CONFIRMED: "Create this ticket", CHANGED: "Change the draft", STOPPED: "Stop"},
    "reproduction": {CONFIRMED: "This shows the bug", CHANGED: "Not the bug yet", STOPPED: "Stop"},
    "retry_choice": {CONFIRMED: "Retry", CHANGED: "Clarify again", STOPPED: "Stop"},
    "advance": {CONFIRMED: "Go to the next phase", CHANGED: "Not now", STOPPED: "Stop"},
    # The clarification questions triage drafted, before they are posted on the ticket.
    "questions": {CONFIRMED: "Post these questions", CHANGED: "Change the questions", STOPPED: "Stop"},
    # Publish & prove: statement (b), the authorised follow-up intent, the declared exception.
    "publication": {CONFIRMED: "Publish this page", CHANGED: "Change the documentation", STOPPED: "Stop"},
    "followup": {CONFIRMED: "Create this follow-up", CHANGED: "Change its summary", STOPPED: "Stop"},
    "exception": {CONFIRMED: "Take the exception", CHANGED: "No exception: end blocked", STOPPED: "Stop"},
    "decisions": {CONFIRMED: "Ship it: push and open the pull request", CHANGED: "Send my answers to the agent",
                  STOPPED: "Stop"},
    "readiness": {CONFIRMED: "Ready: start building", CHANGED: "Answer the questions, then build", STOPPED: "Stop"},
    "interview": {CONFIRMED: "Write the spec with the proposed answers", CHANGED: "Answer the questions, then write",
                  STOPPED: "Stop"},
}


# Statement (a) (``documentation/acceptance``): its own actions, never confirm/change/stop.
MAX_REPLY_CHARS_INPUT = 100_000  # a transport guard, never a cut of a real answer
ACCEPTANCE_LABELS = {"accept": "Accept (observed on the named environment)", "not_testable_yet": "Not testable yet",
                     "reject_acceptance": "Reject"}
REJECT_INPUT = {"name": "reason", "kind": "text", "label": "Why is it rejected?", "default": "", "required": True}
FOLLOWUP_CHANGE_INPUT = {"name": "reason", "kind": "text", "label": "The follow-up's summary instead", "default": "",
                         "required": True}
DECISIONS_INPUT = {"name": "reason", "kind": "text", "label": "Your answers and decisions for the agent",
                   "default": "", "required": True, "max_length": MAX_REPLY_CHARS_INPUT}
READINESS_INPUT = {**DECISIONS_INPUT, "label": "Your answers to the open questions"}


# Subjects whose "change" carries the product owner's answers to the agent (ticket delivery).
INTERVIEW_INPUT = {**DECISIONS_INPUT, "label": "Your answers to the spec questions"}
_ANSWER_INPUTS = {SUBJECT_DECISIONS: DECISIONS_INPUT, SUBJECT_READINESS: READINESS_INPUT,
                  SUBJECT_INTERVIEW: INTERVIEW_INPUT}
MAX_ANSWER_NOTE_CHARS = 100_200
ACTION_CHECK_AUDIENCE = "check_audience_receipt"
ACTION_NEW_AUDIENCE = "new_audience_receipt"
_CONFIRM_ACTIONS = {"confirm": CONFIRMED, "change": CHANGED, "stop": STOPPED}


# Subjects whose refusal names their first blocker (the test contract has its own coverage message).
_BLOCKER_SUBJECTS = frozenset({SUBJECT_PUBLICATION, SUBJECT_FOLLOWUP, "exception"})
_APPROVAL_ACTIONS = {"approve": APPROVED, "reject": REJECTED}
_TOOL_APPROVAL_ACTIONS = {"approve_tool": "approved", "reject_tool": "rejected"}


def _waiting(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.node_state or {}).get("waiting") or {})


def _set_waiting(run: WorkflowRun, waiting: dict[str, Any]) -> None:
    run.node_state = {**dict(run.node_state or {}), "waiting": waiting}


def reply_payload(run: WorkflowRun) -> dict[str, Any]:
    """The server's current question and entry, not a caller-authored reply contract."""
    return {"subject": "reply", "run_id": run.id, "node_id": run.current_node_id,
            "entry": dict(run.node_state or {}).get("entry"), "question": str(_waiting(run).get("question") or "")}


async def prepare_decision(db: AsyncSession, run: WorkflowRun, node: PhasedNode, *, actor_id: str | None) -> None:
    """What a waiting node needs before a person can decide it."""
    waiting = _waiting(run)
    if node.kind == NODE_CONVERSATION:
        from ..clarification_service import create_clarification_question

        session_id = await main_session_id(db, run)
        if session_id:
            iteration = int(dict(run.node_state or {}).get("iteration") or 1)
            question = await create_clarification_question(
                db, session_id=session_id, project_id=run.project_id, run_id=None,
                question_id=f"workflow_run:{run.id}:{node.id}:{iteration}",
                question_text=str(node.config.get("question") or ""), requested_by=run.requested_by,
                context_json={"workflow_run_id": run.id, "node_id": node.id},
            )
            waiting["clarification_id"] = question.id
        if "decider" in node.config:
            _set_waiting(run, waiting)
            payload = reply_payload(run)
            waiting.update(subject="reply", payload=payload, payload_hash=payload_hash(payload))
    elif node.kind == NODE_CONFIRMATION:
        payload = await confirmation_payload(db, run, node)
        waiting.update(subject=payload["subject"], payload=payload, payload_hash=payload_hash(payload))
    elif node.kind == NODE_APPROVAL:
        approval = Approval(
            requested_by=run.requested_by, workspace_id=run.project_id, status="pending",
            action=f"{APPROVAL_ACTION_PREFIX}: {run.title} · {node.title}"[:200],
            reason=str(node.config.get("unlocks") or f"Workflow run {run.id} waits for this approval.")[:2000],
        )
        db.add(approval)
        await db.flush()
        waiting["approval_id"] = approval.id
        run.context = {**dict(run.context or {}), "last_approval_id": approval.id}
    _set_waiting(run, waiting)
    del actor_id


async def authored_decider(db: AsyncSession, run: WorkflowRun) -> bool:
    """Only the current pinned node can declare scoped human decision authority."""
    from .graph import graph_for_run

    if run.workflow_kind != "phased":
        return False
    node = (await graph_for_run(db, run)).nodes.get(str(run.current_node_id or ""))
    return node is not None and "decider" in node.config


async def _may_confirm(db: AsyncSession, run: WorkflowRun, user: User) -> bool:
    from .decider import may_decide
    from .graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes.get(str(run.current_node_id or ""))
    return node is not None and await may_decide(db, run, node, user)


async def _may_allow_tool(db: AsyncSession, run: WorkflowRun, user: User) -> bool:
    """A run's tool approval: the requester (the session owner) or the run's current responsible person."""
    from .responsible import responsible_decider

    return user.id == run.requested_by or user.id in await responsible_decider(db, run)


async def _audit_decision(db: AsyncSession, run: WorkflowRun, user: User, resolution: Any, decision: Any) -> None:
    from .decider import audit_decider_decision

    await db.flush()
    audit_decider_decision(db, run, user, resolution, node_id=str(decision.node_id or ""),
                           payload_hash=decision.payload_hash, decision_id=decision.id)


async def _viewer_may_approve(db: AsyncSession, run: WorkflowRun, user: User) -> bool:
    if await authored_decider(db, run) and not await _may_confirm(db, run, user):
        return False
    if not await is_global_admin(db, user.id):
        return False
    decision = await decide_four_eyes(db, run.requested_by, user.id, authors=[run.requested_by])
    return decision.status in FOUR_EYES_PASSING_STATUSES


def _acceptance_actions(waiting: dict[str, Any], *, late: bool) -> list[dict[str, Any]]:
    """Statement (a)'s actions: accept only with a named environment and an observed build."""
    blocked = bool(dict(waiting.get("payload") or {}).get("accept_blockers"))
    keys = [*([] if blocked else ["accept"]), *([] if late else ["not_testable_yet"]), "reject_acceptance"]
    return [{"key": key, "label": ACCEPTANCE_LABELS[key],
             "input": dict(REJECT_INPUT) if key == "reject_acceptance" else None,
             **({"tone": "danger"} if key == "reject_acceptance" else {})} for key in keys]


def _s1_paused_actions(run: WorkflowRun) -> list[dict[str, Any]]:
    """Publish & prove: a declared missing-proof pause offers the exception; an expired audience wait a new receipt."""
    actions: list[dict[str, Any]] = []
    pause = dict(dict(run.node_state or {}).get("pause") or {})
    if run.pause_reason == PAUSE_AUDIENCE_UNPROVEN and not pause.get("action_node_id"):
        actions.append({"key": ACTION_NEW_AUDIENCE, "label": "Ask for a new audience check", "input": None})
    if run.pause_reason in EXCEPTION_PAUSE_REASONS:
        actions.append({"key": "take_exception", "label": "Take an exception (with a follow-up)", "input": None,
                        "tone": "danger"})
    return actions


async def decision_actions(db: AsyncSession, run: WorkflowRun, *, user: User | None) -> list[dict[str, Any]]:
    """Current human decision offers; tool approval remains the execution requester's consent."""
    from .actions import REASON_INPUT

    if run.status == STATUS_PAUSED and user is not None and user.id == run.requested_by:
        return _s1_paused_actions(run)
    if run.status != STATUS_WAITING or user is None:
        return []
    waiting = _waiting(run)
    can_confirm = (await _may_confirm(db, run, user) if run.waiting_kind in
                   (WAITING_CONFIRMATION, WAITING_FUNCTIONAL_ACCEPTANCE, WAITING_REPLY) else False)
    if run.waiting_kind == WAITING_REPLY and can_confirm and await authored_decider(db, run):
        return [{"key": "reply", "label": "Answer this question",
                 "payload_hash": payload_hash(reply_payload(run)),
                 "input": {"name": "reply", "kind": "text", "label": "Your answer", "required": True,
                           "max_length": MAX_REPLY_CHARS_INPUT}}]
    if run.waiting_kind == WAITING_FUNCTIONAL_ACCEPTANCE and can_confirm:
        return _acceptance_actions(waiting, late=True)
    if run.waiting_kind == WAITING_AUDIENCE_RECEIPT and user.id == run.requested_by:
        return [{"key": ACTION_CHECK_AUDIENCE, "label": "Check the audience proof now", "input": None}]
    if run.waiting_kind == WAITING_CONFIRMATION and can_confirm:
        if waiting.get("subject") == SUBJECT_FUNCTIONAL_ACCEPTANCE:
            return _acceptance_actions(waiting, late=False)
        labels = CONFIRMATION_LABELS.get(str(waiting.get("subject") or ""), CONFIRMATION_LABELS["advance"])
        actions = [{"key": "confirm", "label": labels[CONFIRMED], "input": None},
                   {"key": "change", "label": labels[CHANGED],
                    "input": dict(FOLLOWUP_CHANGE_INPUT) if waiting.get("subject") == SUBJECT_FOLLOWUP else
                    dict(_ANSWER_INPUTS[waiting["subject"]]) if waiting.get("subject") in _ANSWER_INPUTS else None},
                   {"key": "stop", "label": labels[STOPPED], "input": dict(REASON_INPUT)}]
        if dict(waiting.get("payload") or {}).get("missing") or dict(waiting.get("payload") or {}).get("blockers"):
            actions = actions[1:]  # nothing complete to confirm yet
        return actions
    if run.waiting_kind == WAITING_TOOL_APPROVAL and await _may_allow_tool(db, run, user):
        # The tool approval of a platform action is the session owner's consent, like every chat tool approval, and
        # the run's responsible person's.
        action = str(waiting.get("action") or "the next step")
        return [{"key": "approve_tool", "label": f"Allow {action}", "input": None},
                {"key": "reject_tool", "label": "Do not allow", "input": None, "tone": "danger"}]
    if run.waiting_kind == WAITING_APPROVAL and await _viewer_may_approve(db, run, user):
        return [{"key": "approve", "label": "Approve", "input": None},
                {"key": "reject", "label": "Reject", "input": None, "tone": "danger"}]
    return []
