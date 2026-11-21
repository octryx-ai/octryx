"""The follow-up intent after a rejection and the exception from a declared missing-proof pause."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun, WorkflowRunDecision
from ....time_utils import utc_now
from ..graph import SUBJECT_EXCEPTION, SUBJECT_FOLLOWUP
from ..platform.dispatch import (
    APPROVAL_PENDING,
    CLASS_EXTERNAL,
    CLASS_INVALID,
    CLASS_SAFETY,
    FAILED,
    SUCCEEDED,
    ToolOutcome,
)
from ..records import WorkflowRunError, record_event
from ..states import EXCEPTION_PAUSE_REASONS, STATUS_PAUSED
from .acceptance import (
    _MISSING_PROOF,
    ACTION_TAKE_EXCEPTION,
    FOLLOWUP_ISSUE_TYPE,
    PURPOSE_EXCEPTION,
    PURPOSE_REJECTION,
    STATE_PENDING,
)
from .s1_graph import ROUTE_BLOCKED, ROUTE_EXCEPTION, facts, set_facts


def _first_line(text: str, limit: int = 240) -> str:
    return " ".join(str(text or "").split())[:limit]


async def followup_payload(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    """The exact follow-up issue the requester authorises (never written because a draft asked for it)."""
    from ..platform.jira import _project_key

    followup = dict(facts(run).get("followup") or {})
    payload: dict[str, Any] = {"subject": SUBJECT_FOLLOWUP}
    if not followup:
        return {**payload, "missing": "Nothing in this run asks for a follow-up."}
    purpose = str(followup.get("purpose") or "")
    ticket = run.ticket_key or run.title
    published = dict(facts(run).get("publication") or {})
    page = (f"Published page {published.get('page_id')} version {published.get('version')}"
            + (f" (acceptance pending as of {published.get('acceptance_as_of')})"
               if published.get("acceptance_as_published") == STATE_PENDING else "")
            + "; it is not edited by this follow-up.") if published else "Nothing was published."
    if purpose == PURPOSE_REJECTION:
        summary = f"Follow-up of {ticket}: functional acceptance rejected"
        description = (f"The functional acceptance of {ticket} (workflow run {run.id}) was rejected"
                       f"{' after the publication' if followup.get('late') else ''}: {followup.get('reason')}.\n\n"
                       f"{page}\nNo revert was made; a new run (bug fix C or change B) decides the fix.")
    else:
        summary = f"Follow-up of {ticket}: missing proof"
        description = (f"Workflow run {run.id} ends with a declared exception ({followup.get('reason')}). "
                       f"Missing proof: {followup.get('missing_proof')}. Owner: {followup.get('owner')}.\n\n{page}")
    summary = _first_line(str(followup.get("summary_override") or summary))
    project_key = await _project_key(db, run, {})
    payload.update(purpose=purpose, reason=followup.get("reason"), missing_proof=followup.get("missing_proof"),
                   owner=followup.get("owner"), late=bool(followup.get("late")), project_key=project_key,
                   issue_type=FOLLOWUP_ISSUE_TYPE, summary=summary, description=description[:4000])
    if not project_key:
        payload["missing"] = "No Jira project is known for the follow-up (the run has no Work item or ticket)."
    return payload


async def authorise_followup(db: AsyncSession, run: WorkflowRun, decision: WorkflowRunDecision,
                             payload: dict[str, Any]) -> None:
    del db
    followup = dict(facts(run).get("followup") or {})
    set_facts(run, followup={**followup, "authorised": {
        "decision_id": decision.id, "payload_hash": decision.payload_hash,
        **{key: payload.get(key) for key in ("project_key", "issue_type", "summary", "description")}}})


def change_followup(run: WorkflowRun, text: Any) -> None:
    """The requester's own summary for the follow-up; the card shows it again for a new authorisation."""
    summary = _first_line(str(text or ""))
    if not summary:
        raise WorkflowRunError("followup_summary_required", "Say what the follow-up should be called instead.", 422)
    followup = dict(facts(run).get("followup") or {})
    followup.pop("authorised", None)
    set_facts(run, followup={**followup, "summary_override": summary})


async def followup_create(db: AsyncSession, run: WorkflowRun) -> ToolOutcome:
    from ..platform.dispatch import dispatch_tool

    followup = dict(facts(run).get("followup") or {})
    created = dict(followup.get("created") or {})
    if created.get("key"):
        return ToolOutcome(SUCCEEDED, {"ticket_id": created["key"], "status": "existing"})
    authorised = dict(followup.get("authorised") or {})
    if not authorised:
        return ToolOutcome(FAILED, reason="the follow-up was not authorised by the requester",
                           failure_class=CLASS_SAFETY)
    outcome = await dispatch_tool(db, run, "create_jira_ticket", {
        "project_key": authorised["project_key"], "summary": authorised["summary"],
        "description": authorised["description"], "issue_type": authorised["issue_type"],
        "labels": ["workflow-run", "follow-up"]}, capability_class="deliver")
    if outcome.state == APPROVAL_PENDING or not outcome.ok:
        return outcome
    key = str(outcome.result.get("ticket_id") or outcome.result.get("key") or "")
    if not key:
        return ToolOutcome(FAILED, outcome.result, "Jira answered without the follow-up's key; check Jira before a "
                                                   "retry", failure_class=CLASS_EXTERNAL)
    set_facts(run, followup={**followup, "created": {"key": key, "at": utc_now().isoformat()}})
    record_event(db, run, "documentation_followup_created", node_id=run.current_node_id,
                 detail={"key": key, "purpose": followup.get("purpose")})
    return ToolOutcome(SUCCEEDED, {"ticket_id": key})


async def followup_readback(db: AsyncSession, run: WorkflowRun) -> tuple[ToolOutcome, str]:
    """The created follow-up must read back as authorised; then a rejection ends ``blocked``, an exception goes on
    to its confirmation."""
    from ..platform.dispatch import dispatch_tool

    followup = dict(facts(run).get("followup") or {})
    key = str(dict(followup.get("created") or {}).get("key") or "")
    authorised = dict(followup.get("authorised") or {})
    if not key or not authorised:
        return ToolOutcome(FAILED, reason="no authorised follow-up was created", failure_class=CLASS_INVALID), FAILED
    read = await dispatch_tool(db, run, "get_jira_ticket", {"ticket_id": key}, capability_class="read_only")
    if not read.ok:
        return read, FAILED
    problems = []
    if _first_line(str(read.result.get("summary") or "")) != authorised["summary"]:
        problems.append("summary")
    issue_type = str(read.result.get("issue_type") or "")
    if issue_type.lower() != str(authorised["issue_type"]).lower():
        problems.append("issue type")
    if str(read.result.get("ticket_id") or "") != key:
        problems.append("issue identity")
    if str(read.result.get("description") or "").strip() != str(authorised["description"]).strip():
        problems.append("description")
    if problems:
        return ToolOutcome(FAILED, {"mismatch": problems}, f"the follow-up {key} does not read back as authorised "
                           f"({', '.join(problems)})", failure_class=CLASS_EXTERNAL), FAILED
    url = str(read.result.get("source_url") or read.result.get("url") or "")
    set_facts(run, followup={**followup, "readback": {
        "key": key, "url": url if url.lower().startswith(("https://", "http://")) else "",
        "summary": authorised["summary"], "status": read.result.get("status"), "at": utc_now().isoformat()}})
    route = ROUTE_EXCEPTION if followup.get("purpose") == PURPOSE_EXCEPTION else ROUTE_BLOCKED
    return ToolOutcome(SUCCEEDED, {"ticket_id": key, "route": route}), route


async def exception_payload(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    del db
    followup = dict(facts(run).get("followup") or {})
    readback = dict(followup.get("readback") or {})
    payload: dict[str, Any] = {"subject": SUBJECT_EXCEPTION, "reason": followup.get("reason"),
                               "missing_proof": followup.get("missing_proof"), "owner": followup.get("owner"),
                               "followup_key": readback.get("key"), "followup_url": readback.get("url") or None}
    if followup.get("purpose") != PURPOSE_EXCEPTION or followup.get("reason") not in EXCEPTION_PAUSE_REASONS:
        payload["missing"] = "An exception is taken only from a declared missing-proof pause."
    elif not followup.get("owner"):
        payload["missing"] = "The exception names no owner."
    elif not readback.get("key"):
        payload["missing"] = "The follow-up was not created and read back yet."
    else:
        payload["statement"] = (f"The run ends done with an exception: {followup.get('missing_proof')} stays "
                                f"missing; follow-up {readback.get('key')} owns it (owner {followup.get('owner')}).")
    return payload


async def take_exception(db: AsyncSession, run: WorkflowRun, *, user: User) -> None:
    """From a declared missing-proof pause only: open the follow-up intent the exception will be bound to."""
    from ..engine import restart_at
    from ..graph import NODE_CONFIRMATION, graph_for_run
    from ..pause import record_decision

    if run.status != STATUS_PAUSED or run.pause_reason not in EXCEPTION_PAUSE_REASONS:
        raise WorkflowRunError("exception_not_allowed", "An exception is taken only from a declared missing-proof "
                                                        "pause (audience unproven, documentation missing, acceptance "
                                                        "timeout).")
    if user.id != run.requested_by:
        raise WorkflowRunError("not_requester", "Only the run's requester takes an exception.", 403)
    graph = await graph_for_run(db, run)
    entry = next((node for node in graph.ordered_nodes() if node.kind == NODE_CONFIRMATION
                  and node.config.get("subject") == SUBJECT_FOLLOWUP), None)
    if entry is None or not any(node.kind == NODE_CONFIRMATION and node.config.get("subject") == SUBJECT_EXCEPTION
                                for node in graph.nodes.values()):
        raise WorkflowRunError("exception_not_offered", "This workflow version offers no exception.")
    reason = str(run.pause_reason)
    followup = {"purpose": PURPOSE_EXCEPTION, "reason": reason, "missing_proof": _MISSING_PROOF[reason],
                "owner": run.requested_by, "from_node": run.current_node_id, "at": utc_now().isoformat()}
    record_decision(db, run, kind="pause", subject=reason, action=ACTION_TAKE_EXCEPTION,
                    payload={k: followup[k] for k in ("reason", "missing_proof", "owner", "from_node")},
                    user_id=user.id)
    set_facts(run, followup=followup)
    await restart_at(db, run, entry.id, actor_id=user.id)
