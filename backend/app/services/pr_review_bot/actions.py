"""The ``pr-review-bot`` workflow's own steps (``pr_review.*``), definition-only platform actions (concept §4)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ..observability.review_bot_metrics import count_review
from ..workflow_runs import safe_git
from ..workflow_runs.platform.dispatch import FAILED, SUCCEEDED, ToolOutcome, dispatch_tool
from .diff_lines import parse_diff
from .fix import FIX_PREPARE, FIX_REPORT, FIX_SCOPE
from .fix import HANDLERS as FIX_HANDLERS
from .incremental import incremental_pass, reviewer_findings
from .providers import POST_TOOLS
from .publish_steps import filtered_review, post_facts, record_posted, with_caller_findings
from .render import MARKER, STATUS_CONTEXT, ReviewPost, build_post
from .run_facts import facts_of as _facts
from .run_facts import post_target as _target
from .run_facts import set_facts as _set_facts

logger = logging.getLogger(__name__)

PREPARE, PUBLISH, REPORT_FAILURE = "pr_review.prepare", "pr_review.publish", "pr_review.report_failure"
EXPLAIN = "pr_review.explain"  # ``@octryx explain`` (``explain``)
ACTION_KEYS = (PREPARE, PUBLISH, REPORT_FAILURE, EXPLAIN, FIX_PREPARE, FIX_SCOPE, FIX_REPORT)


async def _run_url(db: AsyncSession, run: WorkflowRun) -> str:
    from ..workflow_runs.octryx.contract import run_link
    from ..workflow_runs.records import main_session_id

    link = run_link(run, await main_session_id(db, run)) or ""
    return link if link.startswith("https://") else str(_facts(run).get("url") or "")


async def _post(db: AsyncSession, run: WorkflowRun, commit: str, **post: Any) -> ToolOutcome:
    target = _target(run)
    if target is None:
        return ToolOutcome(FAILED, reason="the run names no pull request of a GitHub, GitLab or Bitbucket repository")
    provider, args = target
    status = post.pop("status", None)
    if status is not None:
        post["commit_status"] = {**status, "context": STATUS_CONTEXT, "target_url": await _run_url(db, run)}
    return await dispatch_tool(db, run, POST_TOOLS[provider], {**args, "commit": commit, **post},
                               capability_class="deliver")


async def prepare(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    from ..workflow_runs.platform.scm import checkout

    checked = await checkout(db, run, {"base_branch": str(_facts(run).get("target_branch") or ""), "review_only": True})
    if not checked.ok:
        return checked
    code, head, _err = await safe_git.git(str(checked.result.get("local_path") or ""), "rev-parse", "HEAD")
    if code != 0 or not head.strip():
        return ToolOutcome(FAILED, reason="the checked-out pull request has no head commit")
    root, merge_base = str(checked.result.get("local_path") or ""), str(checked.result.get("base_sha") or "")
    _set_facts(run, reviewed_sha=head.strip(), merge_base=merge_base)
    await _check_callers(run, root, merge_base)
    await _plan_pass(db, run, root, head.strip(), merge_base)
    from .review_context import gather  # ticket, specification, code graph (stage E)

    _set_facts(run, **await gather(db, run, _facts(run), root, merge_base, head.strip()))
    _set_facts(run, scan_job=await _offer_scan(db, run, root, head.strip()))
    pending = await _post(db, run, head.strip(), status={"state": "pending", "description": "Octryx is reviewing"})
    return pending if not pending.ok else ToolOutcome(SUCCEEDED, {"reviewed_sha": head.strip()})


async def _offer_scan(db: AsyncSession, run: WorkflowRun, root: str, head: str) -> dict[str, Any]:
    from .scan_job import offer_scan

    try:
        async with db.begin_nested():
            return await offer_scan(db, run, root=root, head=head, diff=await _diff(run))
    except Exception as error:  # noqa: BLE001 - the review goes on without the scan, and says so
        logger.warning("pr_review_bot.scan_offer_failed run=%s", run.id, exc_info=True)
        return {"notes": [f"scan not started ({type(error).__name__})"]}


async def _plan_pass(db: AsyncSession, run: WorkflowRun, root: str, head: str, merge_base: str) -> None:
    from .incremental import delta_base, previous_pass, seed

    previous_run, previous = await previous_pass(db, run)
    if previous.get("ignored"):
        _set_facts(run, ignored=list(previous["ignored"]))  # ``@octryx ignore`` holds for the pull request
    if _facts(run).get("force_full"):  # ``@octryx review full`` (stage D)
        _set_facts(run, incremental={"full_because": "a full review was requested", "previous_run": ""})
        return
    delta = await delta_base(root, previous_run, previous, head=head, merge_base=merge_base,
                             target=str(_facts(run).get("target_branch") or ""))
    if not delta.incremental:
        _set_facts(run, incremental={"full_because": delta.full_because, "previous_run": delta.previous_run})
        return
    seeded = seed(previous)
    run.context = {**dict(run.context or {}), "base_sha": delta.base, **({"review": seeded} if seeded else {})}
    _set_facts(run, incremental={"from": delta.base, "previous_run": delta.previous_run,
                                 "open_before": len(previous.get("open_findings") or [])},
               previous_pass={"open_findings": list(previous.get("open_findings") or []),
                              "walkthrough": list(previous.get("walkthrough") or []),
                              "acceptance": list(previous.get("acceptance") or [])})


async def _check_callers(run: WorkflowRun, root: str, base: str) -> None:
    from .callers import check_callers

    if not root or not base:
        return
    checked = await check_callers(root, base)
    _set_facts(run, callers={"findings": checked.findings, "not_checked": checked.not_checked,
                             "changes": checked.changes})
    if checked.changes:
        run.context = {**dict(run.context or {}), "review_context_sections": [
            {"title": "signatures changed by this pull request and their calls", "text": checked.context()}]}


async def _diff(run: WorkflowRun) -> str:
    context = dict(run.context or {})
    # The whole pull request (its merge base), also on an incremental pass: inline comments sit on its diff.
    root = str(context.get("local_path") or "")
    base = str(_facts(run).get("merge_base") or context.get("base_sha") or "")
    head = str(_facts(run).get("reviewed_sha") or "")
    if not root or not base or not head:
        return ""
    code, text, _err = await safe_git.git(root, *safe_git.DIFF, "--no-renames", base, head)
    return text if code == 0 else ""


async def publish(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    review, facts = dict(dict(run.context or {}).get("review") or {}), _facts(run)
    passed = incremental_pass(review, facts)
    if passed is not None:
        review = passed.review
    review = filtered_review(review, facts, passed)
    reviewer = reviewer_findings(list(review.get("findings") or []))
    review = with_caller_findings(review, list(dict(facts.get("callers") or {}).get("findings") or []))
    commit = str(facts.get("reviewed_sha") or "")
    provider = (_target(run) or ("", {}))[0]
    if not review.get("verdict") or not commit:
        return ToolOutcome(FAILED, reason="no review verdict to post")
    from . import threads
    from .ci_results import read_ci
    from .incremental import superseded_by

    ci = await read_ci(db, run, commit)
    review = with_caller_findings(review, ci.findings)
    from .scan_job import read_scan

    scan = await read_scan(db, dict(facts.get("scan_job") or {}))  # the device's scanners, as findings
    review = with_caller_findings(review, list(scan.get("findings") or []))
    newer = await superseded_by(db, run)  # a push since: only this commit's status, the newer run posts the rest

    async def post_threads(**answers: Any) -> ToolOutcome:
        return await _post(db, run, commit, **answers)

    answered = [] if newer else await threads.answer(post_threads, passed, commit)
    post = await _build(db, run, review, facts, passed=passed, commit=commit, provider=provider, ci=ci, scan=scan,
                        answered=answered)
    if newer:
        outcome = await _post(db, run, commit, status={
            "state": post.state, "description": f"Superseded by a newer push · {post.description}"})
        count_review(provider, str(review.get("verdict")), "superseded" if outcome.ok else "failed")
        _set_facts(run, superseded_by=newer)
        return outcome
    outcome = await _post(db, run, commit, summary=post.summary, marker=MARKER,
                          comments=[comment.to_dict() for comment in post.comments],
                          status={"state": post.state, "description": post.description})
    count_review(provider, str(review.get("verdict")), "posted" if outcome.ok else "failed")
    if outcome.ok:
        await record_posted(db, run, provider=provider, review=review, post=post, outcome=outcome, passed=passed,
                            commit=commit, facts=facts, reviewer=reviewer, answered=answered)
    return outcome


async def _build(db: AsyncSession, run: WorkflowRun, review: dict[str, Any], facts: dict[str, Any], *, passed: Any,
                 commit: str, provider: str, ci: Any, scan: dict[str, Any], answered: list[Any]) -> ReviewPost:
    from .settings import repository_record, settings_of

    policy = settings_of(await repository_record(db, str(run.project_id), str(run.repository or ""))).status_policy
    from .suggestion_names import sources

    checked = await sources(str(dict(run.context or {}).get("local_path") or ""),
                            str(_facts(run).get("reviewed_sha") or ""), list(review.get("findings") or []))
    files = parse_diff(await _diff(run))
    return build_post(review, files, provider=provider, facts=await post_facts(
        db, run, review, facts, passed=passed, commit=commit, policy=policy, checked=checked, ci=ci, scan=scan,
        answered=answered))


async def report_failure(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    commit = str(_facts(run).get("reviewed_sha") or _facts(run).get("head_sha") or "")
    failure = next(reversed(list(dict(dict(run.context or {}).get("actions") or {}).values())), {})
    reason = str(dict(failure).get("reason") or "a review step failed")
    status = {"state": "error", "description": f"Octryx review failed: {reason}"}
    posted = await _post(db, run, commit, status=status) if commit else ToolOutcome(
        FAILED, reason="the run names no head commit to mark")
    _set_facts(run, failure={"reason": reason, "status_posted": posted.ok,
                             **({"post_error": posted.reason} if not posted.ok else {})})
    count_review((_target(run) or ("", {}))[0], "none", "failed")
    if not posted.ok:
        why = f"{reason}; the error status was not posted: {posted.reason}"
        return ToolOutcome(FAILED, {"reason": reason}, why[:500], failure_class=posted.failure_class)
    return ToolOutcome(SUCCEEDED, {"reason": reason})


async def _explain(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    from .explain import explain

    return await explain(db, run, params)


HANDLERS = {PREPARE: prepare, PUBLISH: publish, REPORT_FAILURE: report_failure, EXPLAIN: _explain,
            **FIX_HANDLERS}  # ``pr-fix`` (``fix``)


def is_pr_review_action(key: str) -> bool:
    return key in HANDLERS


async def run_pr_review_action(db: AsyncSession, run: WorkflowRun, key: str,
                               params: dict[str, Any]) -> tuple[ToolOutcome, str]:
    outcome = await HANDLERS[key](db, run, params)
    return outcome, SUCCEEDED if outcome.ok else FAILED


__all__ = ["ACTION_KEYS", "EXPLAIN", "HANDLERS", "PREPARE", "PUBLISH", "REPORT_FAILURE", "is_pr_review_action",
           "run_pr_review_action"]
