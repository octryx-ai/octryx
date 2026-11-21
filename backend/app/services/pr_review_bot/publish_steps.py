"""The parts of ``pr_review.publish`` (``actions``) that need no post of their own: the review it posts, the facts
the summary shows, and what a posted review records on the run."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ..observability.review_bot_metrics import count_findings
from ..workflow_runs.platform.dispatch import ToolOutcome
from .incremental import blocking_ids
from .render import ReviewPost
from .run_facts import set_facts


def with_caller_findings(review: dict[str, Any], found: list[dict[str, Any]]) -> dict[str, Any]:
    """The reviewer's verdict with the caller check's findings: a call the change breaks is high whatever the model
    said (a reviewer that sees only the diff can pass a change whose callers break). A reviewer
    finding on the same file and line already says it."""
    if not found or not review.get("verdict"):
        return review
    seen = {(str(item.get("file")), item.get("line"))
            for item in review.get("findings") or [] if isinstance(item, dict)}
    # A CI finding names a check, not a line: each one counts (they all sit on "(CI)" line 1).
    added = [item for item in found if item.get("source") == "ci" or (str(item.get("file")), item.get("line"))
             not in seen]
    if not added:
        return review
    return {**review, "verdict": "changes", "findings": [*list(review.get("findings") or []), *added]}


def filtered_review(review: dict[str, Any], facts: dict[str, Any], passed: Any) -> dict[str, Any]:
    """The review without the findings ``@octryx ignore`` dropped, with one acceptance row per ticket criterion."""
    if facts.get("ignored"):
        from .ignore import without_ignored

        kept = without_ignored(list(review.get("findings") or []), list(facts["ignored"]))
        blocking_left = any(item.get("severity") in ("high", "medium") and not item.get("nonblocking")
                            for item in kept)
        review = {**review, "findings": kept, **({"verdict": "pass"} if not blocking_left else {})}
    criteria = list(dict(facts.get("ticket") or {}).get("criteria") or [])
    if criteria:  # one row per parsed criterion, also when the reviewer left the table out
        from .ticket_context import acceptance_rows

        previous = list(dict(facts.get("previous_pass") or {}).get("acceptance") or []) if passed else []
        review = {**review, "acceptance": acceptance_rows(criteria, list(review.get("acceptance") or []), previous)}
    return review


async def seat_reviewer(db: AsyncSession, run: WorkflowRun) -> str:
    """Whose seat gave the review (the newest seat session of the run), as the footer names it; ``''`` on the
    company route."""
    from sqlalchemy import select

    from ...models import WorkflowRunEvent
    from ..workflow_runs.review.seat import EVENT_SEAT_SESSION

    detail = (await db.execute(select(WorkflowRunEvent.detail).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT_SEAT_SESSION,
    ).order_by(WorkflowRunEvent.created_at.desc()).limit(1))).scalar_one_or_none()
    from .seat_choice import seat_login

    seat_user = str(dict(detail or {}).get("seat_user_id") or "") if detail else ""
    return await seat_login(db, seat_user, str(run.repository or "")) if seat_user else ""


async def post_facts(db: AsyncSession, run: WorkflowRun, review: dict[str, Any], facts: dict[str, Any], *,
                     passed: Any, commit: str, policy: Any, checked: Any, ci: Any, scan: dict[str, Any],
                     answered: list[Any]) -> dict[str, Any]:
    """The facts ``render.build_post`` shows besides the review: footer, status policy, incremental pass."""
    from . import threads

    return {"status_policy": policy,
        "sources": checked,
        "sha": commit, "model": review.get("reviewer_model"), "route": review.get("reviewer_route_used"),
        "seat_of": await seat_reviewer(db, run) if review.get("reviewer_route_used") == "seat" else "",
        "run_id": run.id, "authored_by_run": facts.get("authored_by_run"),
        "not_checked": dict(facts.get("callers") or {}).get("not_checked") or [],
        "ci_pending": ci.pending, "ci_unread": ci.unread, "threads": threads.note(answered),
        "ticket": facts.get("ticket"), "spec": facts.get("spec"), "graph": facts.get("graph"),
        "triage": facts.get("triage"), "scan": {key: scan.get(key) for key in ("tools", "dropped", "notes")},
        **({"incremental": {"from": dict(facts.get("incremental") or {}).get("from"), "fixed": passed.fixed,
                            "withdrawn": passed.withdrawn, "still_open": passed.still_open, "new": passed.new}}
           if passed is not None else {})}


async def record_posted(db: AsyncSession, run: WorkflowRun, *, provider: str, review: dict[str, Any],
                        post: ReviewPost, outcome: ToolOutcome, passed: Any, commit: str, facts: dict[str, Any],
                        reviewer: list[Any], answered: list[Any]) -> None:
    """A posted review: its metrics, what became of the earlier findings, and the open findings for the next pass."""
    from . import threads

    count_findings(provider, post.placed, str(run.repository or ""))
    if passed is not None and passed.fixed:  # what became of the earlier findings (F3)
        from ..workflow_runs.corrections import review_fixed
        from .outcomes import count_pass

        await review_fixed(db, run, {"dropped": [{**dict(item), "dropped": "fixed"} for item in passed.fixed]},
                           before_sha=str(dict(facts.get("incremental") or {}).get("from") or ""),
                           after_sha=commit)
        await count_pass(run, provider, passed.fixed, str(dict(run.context or {}).get("local_path") or ""),
                         str(dict(facts.get("incremental") or {}).get("from") or ""), commit)
    if passed is not None and passed.withdrawn:  # a person showed it does not apply: an ignore, for precision
        from .outcomes import count_ignored

        for item in passed.withdrawn:
            count_ignored(provider, str(run.repository or ""), item)
    set_facts(run, posted={"state": post.state, "inline": len(post.comments), "blocking": blocking_ids(review),
                           "summary_comment_id": outcome.result.get("summary_comment_id"),
                           "inline_refused": bool(outcome.result.get("inline_refused"))},
              open_findings=threads.remember(reviewer, post.comments, outcome.result.get("inline_ids"),
                                             answered),
              threads=answered, walkthrough=list(review.get("walkthrough") or []),
              acceptance=list(review.get("acceptance") or []))


__all__ = ["filtered_review", "post_facts", "record_posted", "seat_reviewer", "with_caller_findings"]
