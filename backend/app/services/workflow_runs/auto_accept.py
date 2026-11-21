"""The product owner is asked at the start; after that the work goes on by itself.

A ``user_confirmation`` node with ``config.auto_accept: "review_passed"`` (ticket delivery's "ship it or answer")
is confirmed by the platform, without a person, when everything the platform can check says the work is done:

- the independent review's last verdict is ``pass`` with no finding of severity high or medium;
- the run has a task list and every task is ``verified`` (``task_status``).

Otherwise the work goes back to the agent ``config.auto_revise`` times; after those revisions the node is confirmed
when no finding of severity high is open (and every task is verified where the node needs tasks): the medium and
low findings left become notes for the product owner (``context.review_notes``, also on the decision). Most
review verdicts ask for changes, revisions rarely converge, and a single cosmetic medium would keep a finished story
waiting for the product owner. Only a high finding (an acceptance
criterion or a confirmed decision broken, a security risk, a task a user cannot complete) still asks the person. The
decision is recorded like a person's (``decided_by`` empty, event
``auto_accepted`` with the reason), so the product owner sees afterwards what went through and can still answer
on the pull request or start a follow-up.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from .records import record_event

AUTO_ACCEPT_KEY = "auto_accept"
RULE_REVIEW_PASSED = "review_passed"
#: A story of an epic: the product owner answered once for the whole epic in its spec round (ask
#: once at the start); the story's readiness questions are answered by their proposals.
RULE_EPIC_STORY = "epic_story"
EPIC_STORY_ANSWER = (
    "This story belongs to epic {epic}; the product owner answered once for the whole epic (its specification, "
    "section Decisions, and its design system). Take every answer the readiness check proposed. Where it proposed "
    "none, decide by the specification and the design system, choose the simplest option a user would expect, and "
    "name each such decision in your summary as an assumption.")
EVENT_AUTO_ACCEPTED = "auto_accepted"
EVENT_AUTO_REVISED = "auto_revised"


REVISE_ON_KEY = "revise_on"
REVISE_ON_HIGH = "high"


def accept_reason(run: WorkflowRun, *, needs_tasks: bool = True, after_revisions: int | None = None,
                  revise_on: str | None = None, prefer: tuple[str, ...] = ()) -> str:
    """Why the platform may confirm for the product owner; "" when it may not. ``needs_tasks=False``: a run
    without a task list (spec writing) passes on the review alone. ``after_revisions``: the automatic revisions are
    used up (their number), so only a high finding blocks; medium and low ones are notes. ``revise_on="high"``
    (team delivery): only a high finding is worth a revision at all, so the node accepts at once
    when none is open and the medium and low findings become notes. A run whose pipeline was skipped (a server run
    has no pipeline runner yet) cannot verify its tasks: the review decides alone, and the reason says so."""
    from .pipeline import state as pipeline_state
    from .task_list import run_task_list
    from .task_status import VERIFIED

    review = dict(dict(run.context or {}).get("review") or {})
    findings = [dict(item) for item in review.get("findings") or [] if isinstance(item, dict)]
    severities = {str(item.get("severity") or "") for item in findings}
    if after_revisions is None and revise_on != REVISE_ON_HIGH:
        if review.get("verdict") != "pass" or severities & {"high", "medium"}:
            return ""
        passed = "review passed"
    else:
        if review.get("verdict") not in ("pass", "changes") or "high" in severities:
            return ""
        notes = f"; {len(findings)} medium or low findings are notes for the product owner" if findings else ""
        passed = (f"no high finding after {after_revisions} automatic revisions{notes}" if after_revisions is not None
                  else f"no high finding (revise only on high){notes}")
    tasks = run_task_list(run, prefer)
    lenient = after_revisions is not None or revise_on == REVISE_ON_HIGH
    if not tasks and not needs_tasks:
        return f"{passed} without a medium or high finding" if not lenient else passed
    if tasks and pipeline_state(run).get("state") == "skipped":
        return f"{passed}; {len(tasks)} tasks not verified: the pipeline was skipped on the server"
    if not tasks or any(item.get("status") != VERIFIED for item in tasks):
        return ""
    return f"{passed}, all {len(tasks)} tasks verified"


REVIEW_NOTES_KEY = "review_notes"


def review_notes(run: WorkflowRun) -> list[dict[str, Any]]:
    """The open findings below high of the last verdict: what the product owner reads after an automatic accept."""
    review = dict(dict(run.context or {}).get("review") or {})
    return [dict(item) for item in review.get("findings") or []
            if isinstance(item, dict) and str(item.get("severity") or "") in ("medium", "low")]


def _confirm(db: AsyncSession, run: WorkflowRun, subject: str, payload: dict[str, Any], reason: str) -> None:
    """Record the platform's confirmation like a person's, with the notes kept on the run and the decision."""
    from .graph import CONFIRMED
    from .pause import record_decision

    notes = review_notes(run)
    run.context = {**dict(run.context or {}), REVIEW_NOTES_KEY: notes}
    extra = {REVIEW_NOTES_KEY: notes} if notes else {}
    record_decision(db, run, kind="confirmation", subject=subject, action=CONFIRMED,
                    payload={**payload, "auto_accepted": reason, **extra}, user_id=None)
    record_event(db, run, EVENT_AUTO_ACCEPTED, node_id=run.current_node_id,
                 detail={"reason": reason, "notes": len(notes)})


AUTO_REVISE_KEY = "auto_revise"
REVISIONS_KEY = "auto_revisions"
REVISE_ANSWER = (
    "Automatic revision {n} of {limit} (the product owner answered at the start and is asked only at the end): fix "
    "every finding of the independent review and every task that is not verified yet. Where a finding needs a "
    "product decision, take the simplest option that fits the specification and the design system and name it in "
    "your summary as an assumption.")


async def epic_story_reason(db: AsyncSession, run: WorkflowRun) -> str:
    """Why the readiness answers of this run need no product owner: its work item is a story of an epic."""
    from ...models.runtime.secure_work import WorkItem

    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    epic = str(getattr(item, "epic_key", "") or "").strip()
    return f"story of epic {epic}: the product owner answered for the epic" if epic else ""


async def accept_on_entry(db: AsyncSession, run: WorkflowRun, node: Any) -> bool:
    """A confirmation node with ``auto_accept: "epic_story"`` is confirmed as it is entered when the rule holds:
    the proposals stand as the product owner's answer (``po_answers``), recorded like a person's decision."""
    from ...time_utils import utc_now
    from .graph import CONFIRMED
    from .pause import record_decision

    if dict(node.config or {}).get(AUTO_ACCEPT_KEY) != RULE_EPIC_STORY:
        return False
    reason = await epic_story_reason(db, run)
    if not reason:
        return False
    from ...models.runtime.secure_work import WorkItem

    item = await db.get(WorkItem, run.work_item_id)
    text = EPIC_STORY_ANSWER.format(epic=item.epic_key)
    answers = list(dict(run.context or {}).get("po_answers") or [])
    if not any(isinstance(answer, dict) and answer.get("auto_accepted") == reason for answer in answers):
        # Once per run: every replan and every "changed" loop enters the node again, and
        # each entry would append the same answer to every later contract and to the review.
        answers.append({"text": text, "by": None, "at": utc_now().isoformat(), "auto_accepted": reason})
        run.context = {**dict(run.context or {}), "po_answers": answers}
    subject = str(dict(node.config or {}).get("subject") or "")
    record_decision(db, run, kind="confirmation", subject=subject, action=CONFIRMED,
                    payload={"subject": subject, "auto_accepted": reason}, user_id=None)
    record_event(db, run, EVENT_AUTO_ACCEPTED, node_id=node.id, detail={"reason": reason})
    return True


async def auto_accept(db: AsyncSession, run: WorkflowRun) -> bool:
    """Confirm the waiting node for the product owner when its rule holds; ``True`` when it did."""
    from .engine import resolve_current_node
    from .graph import CONFIRMED, NODE_CONFIRMATION, graph_for_run
    from .states import STATUS_WAITING, WAITING_CONFIRMATION

    if run.status != STATUS_WAITING or run.waiting_kind != WAITING_CONFIRMATION:
        return False
    graph = await graph_for_run(db, run)
    node = graph.nodes.get(run.current_node_id or "")
    from .product_owner_wait import (
        RULE_PRODUCT_OWNER,
        WORKSPACE_OPT_IN,
        wait_for_product_owner,
        workspace_accepts_review,
    )

    rule = node.config.get(AUTO_ACCEPT_KEY) if node is not None and node.kind == NODE_CONFIRMATION else None
    if rule not in (RULE_REVIEW_PASSED, RULE_PRODUCT_OWNER):
        return False
    from .task_list import task_list_nodes

    # "product_owner" (spec-writing's default): the same revisions, then the person decides.
    opted_in = rule == RULE_PRODUCT_OWNER and await workspace_accepts_review(db, run)
    accept = rule == RULE_REVIEW_PASSED or opted_in
    reason = accept_reason(run, needs_tasks=node.config.get("tasks") is not False,
                           revise_on=node.config.get(REVISE_ON_KEY), prefer=task_list_nodes(graph))
    if not reason:
        return await _revise_or_wait(db, run, node, accept=accept)
    from .spec_studio.hooks import agent_open_points, note_open_points

    points = agent_open_points(run)
    if points:
        # Spec Studio: open spec points (no zero-config default, no realistic example …) block the product owner's
        # approval, so the agent fixes them first, within the same automatic revisions as the review's findings.
        note_open_points(run, points)
        return await _revise_or_wait(db, run, node, accept=accept)
    if not accept:
        return await wait_for_product_owner(db, run, node, why=reason)
    waiting = dict(dict(run.node_state or {}).get("waiting") or {})
    payload = dict(waiting.get("payload") or {"subject": str(waiting.get("subject") or "")})
    why = f"{reason} ({WORKSPACE_OPT_IN})" if opted_in else reason
    _confirm(db, run, str(payload.get("subject") or ""), payload, why)
    await resolve_current_node(db, run, CONFIRMED, actor_id=None)
    return True


REVISIONS_LEFT = "findings or open points left after the automatic revisions"


async def _revise_or_wait(db: AsyncSession, run: WorkflowRun, node: Any, *, accept: bool) -> bool:
    from .product_owner_wait import wait_for_product_owner

    return (await _auto_revise(db, run, node, accept=accept)
            or (not accept and await wait_for_product_owner(db, run, node, why=REVISIONS_LEFT)))


ACCEPT_AFTER_REVISIONS_KEY = "accept_after_revisions"


async def _accept_after_revisions(db: AsyncSession, run: WorkflowRun, node: Any, done: int) -> bool:
    """The automatic revisions are used up: confirm when no high finding is open (every task verified where the
    node needs tasks); the medium and low findings left are notes for the product owner.

    A specification (``accept_after_revisions``) is accepted without a task list: a spec review keeps finding
    new points of precision in every round (25, 22, 23 in three rounds); the stories decide such points
    themselves and name them as assumptions (ask once at the start, then automatic)."""
    from .engine import resolve_current_node
    from .graph import CONFIRMED

    if node.config.get(ACCEPT_AFTER_REVISIONS_KEY) is True:
        findings = list(dict(dict(run.context or {}).get("review") or {}).get("findings") or [])
        if any(str(dict(item).get("severity") or "") == "high" for item in findings):
            return False
        reason = f"revised {node.config.get(AUTO_REVISE_KEY)} times, no high finding; {len(findings)} open points " \
                 "go to the stories, which decide them as assumptions"
    else:
        reason = accept_reason(run, needs_tasks=node.config.get("tasks") is not False, after_revisions=done)
        if not reason:
            return False
    subject = str(node.config.get("subject") or "")
    _confirm(db, run, subject, {"subject": subject}, reason)
    await resolve_current_node(db, run, CONFIRMED, actor_id=None)
    return True


ON_OPEN_HIGH_KEY = "on_open_high"
ON_OPEN_HIGH_WAIT = "wait"
ON_OPEN_HIGH_CONTINUE = "continue_with_findings"
ON_OPEN_HIGH_VALUES = (ON_OPEN_HIGH_WAIT, ON_OPEN_HIGH_CONTINUE)
#: Workflows whose decisions gate goes on with open high findings unless the node says otherwise
#: (an epic's stories run unattended; the person who merges decides the findings on the pull request).
CONTINUE_BY_DEFAULT = frozenset({"epic-delivery"})
OPEN_FINDINGS_KEY = "open_findings"
EVENT_ACCEPTED_WITH_OPEN_FINDINGS = "accepted_with_open_findings"
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def on_open_high(node: Any, workflow_key: str | None) -> str:
    """What the gate does when a high finding is still open after the automatic revisions: the node's
    ``config.on_open_high``, else the workflow's default ("continue_with_findings" for epic-delivery,
    "wait" for a person everywhere else)."""
    value = str(dict(node.config or {}).get(ON_OPEN_HIGH_KEY) or "")
    if value in ON_OPEN_HIGH_VALUES:
        return value
    return ON_OPEN_HIGH_CONTINUE if str(workflow_key or "") in CONTINUE_BY_DEFAULT else ON_OPEN_HIGH_WAIT


def on_open_high_errors(graph: Any) -> list[dict[str, str]]:
    """The designer's check of ``on_open_high``: one of its two values, so a typo never silently means "wait"."""
    from .graph import NODE_CONFIRMATION
    from .graph_node_rules import _error, _name

    errors = []
    for node in graph.nodes.values():
        value = dict(node.config or {}).get(ON_OPEN_HIGH_KEY)
        if value is None:
            continue
        if node.kind != NODE_CONFIRMATION or value not in ON_OPEN_HIGH_VALUES:
            errors.append(_error("on_open_high", f"{_name(node)}: on_open_high is set on a confirmation box "
                                                 f"and is one of: {', '.join(ON_OPEN_HIGH_VALUES)}.", node_id=node.id))
    return errors


def open_findings(run: WorkflowRun) -> list[dict[str, Any]]:
    """Every finding of the last verdict, high first: what the person who merges must decide."""
    review = dict(dict(run.context or {}).get("review") or {})
    items = [dict(item) for item in review.get("findings") or [] if isinstance(item, dict)]
    return sorted(items, key=lambda item: _SEVERITY_ORDER.get(str(item.get("severity") or "").lower(), 3))


async def _continue_with_findings(db: AsyncSession, run: WorkflowRun, node: Any, done: int) -> bool:
    """A high finding is still open after the revisions and the node says ``continue_with_findings``: confirm, so the
    run pushes and opens the pull request, with every open finding on top of its description.

    an epic's stories ran unattended until one high finding after two revisions stopped the whole
    chain at the decisions gate overnight; the finding is better decided on the pull request than by waiting."""
    from .engine import resolve_current_node
    from .graph import CONFIRMED
    from .pause import record_decision

    findings = open_findings(run)
    high = sum(1 for item in findings if str(item.get("severity") or "").lower() == "high")
    if on_open_high(node, run.workflow_key) != ON_OPEN_HIGH_CONTINUE:
        return False
    if high:
        reason = (f"{high} high finding{'s' if high != 1 else ''} still open after {done} automatic revisions; "
                  f"continued with all {len(findings)} open findings on the pull request")
    else:
        # No high finding, but a task the review did not see verified (an unattended
        # story must not wait for a person here when nothing high is open): the same rule, the open points go on
        # the pull request for the person who merges.
        reason = (f"no high finding, but not every task verified after {done} automatic revisions; continued with "
                  f"all {len(findings)} open findings on the pull request")
    run.context = {**dict(run.context or {}), OPEN_FINDINGS_KEY: findings, REVIEW_NOTES_KEY: []}
    subject = str(node.config.get("subject") or "")
    record_decision(db, run, kind="confirmation", subject=subject, action=CONFIRMED,
                    payload={"subject": subject, "auto_accepted": reason, OPEN_FINDINGS_KEY: findings}, user_id=None)
    record_event(db, run, EVENT_ACCEPTED_WITH_OPEN_FINDINGS, node_id=node.id,
                 detail={"reason": reason, "high": high, "findings": len(findings)})
    await resolve_current_node(db, run, CONFIRMED, actor_id=None)
    return True


async def _auto_revise(db: AsyncSession, run: WorkflowRun, node: Any, *, accept: bool = True) -> bool:
    """Send the work back to the agent with the review's findings, at most ``config.auto_revise`` times; then the
    product owner decides (ask once at the start, then automatic)."""
    from ...time_utils import utc_now
    from .engine import resolve_current_node
    from .graph import CHANGED
    from .pause import record_decision

    try:
        limit = int(node.config.get(AUTO_REVISE_KEY) or 0)
    except (TypeError, ValueError):
        return False
    context = dict(run.context or {})
    done = int(dict(context.get(REVISIONS_KEY) or {}).get(node.id) or 0)
    if dict(context.get("review") or {}).get("verdict") is None:
        return False
    if done >= limit:
        if not accept:
            return False  # the product owner decides what is left
        return (await _accept_after_revisions(db, run, node, done)
                or await _continue_with_findings(db, run, node, done))
    text = REVISE_ANSWER.format(n=done + 1, limit=limit)
    answers = list(context.get("po_answers") or [])
    answers.append({"text": text, "by": None, "at": utc_now().isoformat(), "auto_revision": done + 1})
    run.context = {**context, "po_answers": answers,
                   REVISIONS_KEY: {**dict(context.get(REVISIONS_KEY) or {}), node.id: done + 1}}
    subject = str(node.config.get("subject") or "")
    record_decision(db, run, kind="confirmation", subject=subject, action=CHANGED,
                    payload={"subject": subject, "auto_revision": done + 1, "text": text}, user_id=None)
    record_event(db, run, EVENT_AUTO_REVISED, node_id=run.current_node_id, detail={"revision": done + 1})
    await resolve_current_node(db, run, CHANGED, actor_id=None)
    return True


__all__ = ["EVENT_ACCEPTED_WITH_OPEN_FINDINGS", "ON_OPEN_HIGH_CONTINUE", "ON_OPEN_HIGH_KEY", "ON_OPEN_HIGH_WAIT",
           "OPEN_FINDINGS_KEY", "on_open_high", "on_open_high_errors", "open_findings", "REVISE_ON_HIGH",
           "REVISE_ON_KEY", "REVIEW_NOTES_KEY", "review_notes", "AUTO_REVISE_KEY", "EVENT_AUTO_REVISED",
           "AUTO_ACCEPT_KEY", "EVENT_AUTO_ACCEPTED", "RULE_EPIC_STORY", "RULE_REVIEW_PASSED", "accept_on_entry",
           "accept_reason", "auto_accept", "epic_story_reason"]
