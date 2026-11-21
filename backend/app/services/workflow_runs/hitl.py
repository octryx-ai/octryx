"""Human-in-the-loop nodes of a phased run: what a waiting run shows and how a person moves it on.

- ``user_conversation``: the run asks its question in the chat banner and waits for the requester's next
  message in the bound session; the reply is recorded on the run and the run continues (the same turn then
  runs the next phase, if one follows).
- ``user_confirmation``, ``approval``, ``watch``: the run waits; how they are decided is in this module's
  decision functions and in the run's actions.

While a run waits, a chat turn in its session is held with the run's state (``held_reason``): nothing runs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ...time_utils import utc_now
from .graph import NODE_CONVERSATION, NODE_WATCH, PhasedNode
from .records import record_event
from .states import (
    EVENT_DECISION,
    WAITING_APPROVAL,
    WAITING_CONFIRMATION,
    WAITING_DEVICE,
    WAITING_REPLY,
    WAITING_REVIEW,
    WAITING_SUB_WORKFLOW,
    WAITING_TOOL_APPROVAL,
    WAITING_WATCH,
)

MAX_REPLY_CHARS = 100_000  # a transport guard, never a cut of a real answer


def _waiting(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.node_state or {}).get("waiting") or {})


def _set_waiting(run: WorkflowRun, waiting: dict[str, Any]) -> None:
    run.node_state = {**dict(run.node_state or {}), "waiting": waiting}


async def enter_waiting_node(db: AsyncSession, run: WorkflowRun, node: PhasedNode, *, actor_id: str | None) -> None:
    """Record what the run waits for; the banner and the Inbox read it from the run."""
    waiting: dict[str, Any] = {"kind": run.waiting_kind, "title": node.title, "since": utc_now().isoformat()}
    if node.kind == NODE_CONVERSATION:
        waiting["question"] = str(node.config.get("question") or "")
    if node.kind == NODE_WATCH:
        waiting["conditions"] = [str(item) for item in node.config.get("conditions") or []]
        waiting["question"] = f"Waiting for: {', '.join(waiting['conditions'])}"
        from .watch import watch_target

        waiting["target"] = watch_target(run, node)
    _set_waiting(run, waiting)
    from .hitl_actions import prepare_decision

    await prepare_decision(db, run, node, actor_id=actor_id)


_HELD = {
    WAITING_REPLY: ("needs_clarification", "The workflow run waits for your reply."),
    WAITING_CONFIRMATION: ("needs_clarification", "The workflow run waits for your confirmation in the run card."),
    WAITING_APPROVAL: ("needs_approval", "The workflow run waits for an approval by another person."),
    WAITING_WATCH: ("needs_clarification", "The workflow run waits for an external state; nothing runs meanwhile."),
    WAITING_SUB_WORKFLOW: ("needs_clarification", "The workflow run waits for its sub-workflow."),
    WAITING_TOOL_APPROVAL: ("needs_approval", "The workflow run waits for the approval of its next step in this chat."),
    WAITING_REVIEW: ("needs_clarification", "The independent reviewer reviews the change; nothing runs meanwhile."),
    WAITING_DEVICE: ("needs_configuration", "The workflow run waits for its device; nothing runs elsewhere meanwhile."),
}


def held_reason(run: WorkflowRun) -> tuple[str, str]:
    """The execution profile state and reason of a turn the run holds."""
    if run.status == "paused":
        pause = dict(dict(run.node_state or {}).get("pause") or {})
        detail = str(pause.get("message") or "")
        return "needs_clarification", (
            "The workflow run is paused" + (f": {detail}" if detail else "") +
            ". Choose in the run card: continue, change the plan, or abort."
        )
    return _HELD.get(run.waiting_kind or "", ("needs_clarification", "The workflow run is waiting."))


async def record_reply(db: AsyncSession, run: WorkflowRun, text: str, *, user: User | None = None) -> None:
    """Answer as the authenticated current decider; an internal call without a user defaults to the
    requester, unless the node has an authored decider."""
    from .decider import audit_decider_decision, require_node_decider
    from .engine import resolve_current_node
    from .hitl_actions import authored_decider, reply_payload
    from .pause import record_decision
    from .records import WorkflowRunError

    reply = str(text or "").strip()[:MAX_REPLY_CHARS]
    if not reply:
        return
    authored = await authored_decider(db, run)
    if user is None:
        if authored:
            raise WorkflowRunError("not_decider", "This authored decision requires the authenticated human actor.", 403)
        user = await db.get(User, run.requested_by) if run.requested_by else None
    if user is None:
        raise WorkflowRunError("not_decider", "A current human must answer this question.", 403)
    resolution = await require_node_decider(db, run, user)
    if run.status != "waiting" or run.waiting_kind != WAITING_REPLY:
        raise WorkflowRunError("not_awaiting_reply", "The run does not wait for this reply.", 409)
    node_id = run.current_node_id or ""
    question_payload = reply_payload(run)
    await _answer_clarification(db, run, reply, actor_id=user.id)
    context = dict(run.context or {})
    context["replies"] = {**dict(context.get("replies") or {}), node_id: reply}
    run.context = context
    if authored:
        decision = record_decision(db, run, kind="conversation", subject="reply", action="answered",
                                   payload={**question_payload, "reply": reply}, user_id=user.id)
        await db.flush()
        audit_decider_decision(db, run, user, resolution, node_id=node_id,
                               payload_hash=decision.payload_hash, decision_id=decision.id)
    else:
        record_event(db, run, EVENT_DECISION, node_id=node_id, actor_id=user.id,
                     detail={"kind": "reply", "chars": len(reply)})
    await resolve_current_node(db, run, None, actor_id=user.id)


async def _answer_clarification(db: AsyncSession, run: WorkflowRun, reply: str, *, actor_id: str) -> None:
    """The run's own question is answered by the same reply (if the send path has not done it already)."""
    from ...models import ClarificationQuestion

    question_id = str(_waiting(run).get("clarification_id") or "")
    question = await db.get(ClarificationQuestion, question_id) if question_id else None
    if question is not None and question.status == "open":
        question.status, question.answer_text = "answered", reply[:20_000]
        question.answered_by, question.answered_at = actor_id, utc_now()


__all__ = ["enter_waiting_node", "held_reason", "record_reply"]
