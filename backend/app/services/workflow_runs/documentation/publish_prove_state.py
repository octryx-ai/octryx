"""Publish & prove's state: ``done`` only with a resolved (a) and a bound proof, the run view and Inbox items."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkflowRunDecision
from ..graph import ACCEPTED, SUBJECT_FUNCTIONAL_ACCEPTANCE
from ..platform.dispatch import CLASS_INVALID, FAILED, SUCCEEDED, ToolOutcome
from ..states import STATUS_WAITING, WAITING_AUDIENCE_RECEIPT, WAITING_FUNCTIONAL_ACCEPTANCE
from .acceptance import _iso, acceptance_state
from .s1_graph import facts


async def done_check(db: AsyncSession, run: WorkflowRun) -> ToolOutcome:
    """``done`` only with a resolved (a) and a valid, currently bound publication proof."""
    from ....models.runtime.documentation_publication import INTENT_SENT_CONFIRMED
    from .s1_graph import latest_intent

    problems: list[str] = []
    state = acceptance_state(run)
    decision = await db.get(WorkflowRunDecision, str(state.get("decision_id") or "")) if state.get(
        "decision_id") else None
    if (state["state"] != ACCEPTED or decision is None or decision.action != ACCEPTED
            or decision.run_id != run.id or decision.kind != "confirmation"
            or decision.subject != SUBJECT_FUNCTIONAL_ACCEPTANCE):
        problems.append("the functional acceptance (a) is not resolved")
    published = dict(facts(run).get("publication") or {})
    intent = await latest_intent(db, run)
    if not published:
        problems.append("nothing was published")
    elif intent is None or intent.id != published.get("intent_id"):
        problems.append("the publication proof is not bound to the run's current publication")
    elif (intent.state != INTENT_SENT_CONFIRMED or str(intent.result_page_id or "") != str(published.get("page_id"))
          or intent.result_version != published.get("version")):
        problems.append("the current publication is not sent and confirmed at the published page version")
    synced = dict(facts(run).get("sync") or {})
    if published and str(synced.get("page_version") or "") != str(published.get("version") or "-"):
        problems.append("Knowledge does not hold the published version")
    # Proofs may precede a deferred functional decision by days. Validate their current bindings and rights,
    # without consuming them a second time. The receipt service owns this single authoritative check.
    from .s1_graph import _call

    proof = await _call("validate_current_publication_proof", db, run)
    if not proof.ok:
        return proof
    if problems:
        return ToolOutcome(FAILED, {"problems": problems}, "not done: " + "; ".join(problems)[:450],
                           failure_class=CLASS_INVALID)
    return ToolOutcome(SUCCEEDED, {"acceptance_decision_id": state.get("decision_id"),
                                   "page_id": published.get("page_id"), "version": published.get("version")})


def publish_prove_view(run: WorkflowRun) -> dict[str, Any] | None:
    """What the run card shows: the immutable published fact and, next to it, the dated (a) decisions."""
    current = facts(run)
    if not current:
        return None
    published = dict(current.get("publication") or {})
    followup = dict(current.get("followup") or {})
    readback = dict(followup.get("readback") or {})
    return {
        "publication": {key: published.get(key) for key in (
            "page_id", "version", "published_at", "acceptance_as_published", "acceptance_as_of")} or None,
        "acceptance": acceptance_state(run),
        "acceptance_history": [{key: item.get(key) for key in ("decision", "at", "late", "reason")}
                               for item in current.get("acceptance_history") or []],
        "audience": {role: bool(dict(value or {}).get("consumed"))
                     for role, value in dict(current.get("audience") or {}).items()},
        "followup": {"purpose": followup.get("purpose"), "key": readback.get("key") or dict(
            followup.get("created") or {}).get("key"), "url": readback.get("url") or None,
            "read_back": bool(readback)} if followup else None,
    }


async def inbox_items(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    """The Inbox entries of the publish & prove waiting kinds: the requester's pending (a), and the audience checks
    this user is the expected principal of (they run the check signed in as themselves)."""
    from ..records import main_session_id

    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.status == STATUS_WAITING,
        WorkflowRun.waiting_kind.in_((WAITING_FUNCTIONAL_ACCEPTANCE, WAITING_AUDIENCE_RECEIPT)))
        .order_by(WorkflowRun.updated_at.desc()).limit(100))).scalars().all()
    items = []
    for run in rows:
        waiting = dict(dict(run.node_state or {}).get("waiting") or {})
        if run.waiting_kind == WAITING_FUNCTIONAL_ACCEPTANCE and run.requested_by == user_id:
            from ..hitl_actions import authored_decider

            if await authored_decider(db, run):
                continue  # an authored decider's personal role Inbox offers it (``role_inbox``), not the requester's
            session_id = await main_session_id(db, run)
            items.append({"kind": "workflow_run_acceptance", "id": run.id, "title": f"Functional acceptance: "
                          f"{run.title}", "created_at": _iso(run.updated_at),
                          "link": {"href": f"/chat?session_id={session_id}", "label": "Decide in the run card"}
                          if session_id else {"tab": "observabilityRuns", "label": "Observability → Runs"},
                          "subtitle": "Published with the acceptance pending; record or reject it"})
        elif run.waiting_kind == WAITING_AUDIENCE_RECEIPT:
            from ....models import DocumentationAudienceReceipt

            challenge_id = str(waiting.get("challenge_id") or "")
            receipt = (await db.execute(select(DocumentationAudienceReceipt).where(
                DocumentationAudienceReceipt.challenge_id == challenge_id,
                DocumentationAudienceReceipt.expected_principal_id == user_id,
                DocumentationAudienceReceipt.state == "issued",
            ))).scalar_one_or_none()
            if receipt is None:
                continue
            items.append({"kind": "workflow_run_audience_receipt", "id": receipt.challenge_id,
                          "title": "Verify documentation access", "created_at": _iso(run.updated_at),
                          "link": {"href": "/chat", "label": "Run the access check"},
                          "proof_action": {"challenge_id": receipt.challenge_id},
                          "subtitle": "Run the assigned check signed in as yourself; no page details are disclosed"})
    return items
