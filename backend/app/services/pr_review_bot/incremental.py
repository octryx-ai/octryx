"""Incremental passes: after a push the bot reviews only what changed since the commit
it last posted a review for, and answers its open findings.

No new table: the state of a pass lives in the run's own facts (``context.pr_review``) when it posts:

- ``reviewed_sha`` and ``merge_base`` (the target branch's merge base it reviewed against);
- ``open_findings``: the reviewer's findings still open after the pass (ids ``F<n>``; the deterministic caller
  and CI findings are recomputed on every pass and never carried);
- ``walkthrough``: the per-file words, carried into a pass whose reviewer writes none.

The next run of the same pull request (``previous_pass``) reviews ``reviewed_sha..head`` when that is a plain
continuation (``delta_base``); otherwise a full pass: no previous post, a target branch that changed or
moved into the pull request (another merge base), a rewritten history (force push, rebase), or an empty delta.

The answer to the open findings is the platform's follow-up review (``review.convergence``): the review node gets
the open findings as its previous verdict (``seed``) and answers each id ``fixed`` / ``not_fixed``. What the
follow-up drops for its own convergence the bot keeps (``effective``):

- an open finding on a file the delta does not touch (``out_of_scope``) is still open: nothing changed there;
- a new finding below ``high`` (``new_not_high``) is posted inline but does not block the status (``nonblocking``):
  a medium bug in a follow-up commit is never swallowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ..workflow_runs import safe_git
from .starter import CONTEXT_KEY, WORKFLOW_KEY, same_head

REVIEW_NODE = "independent_review"
_RECENT_RUNS = 200
_ID = re.compile(r"^F(\d+)$")
_DETERMINISTIC = frozenset({"caller_check", "ci", "scan"})
_CARRIED = ("comment_id", "nonblocking", "answered", "suggested", "replies", "reply_ids")


@dataclass(frozen=True, slots=True)
class Delta:
    """``base`` is the commit the pass reviews from: the previous pass's head (incremental) or ``''`` (full, with
    the reason in ``full_because``)."""

    base: str = ""
    full_because: str = ""
    previous_run: str = ""
    previous: dict[str, Any] = field(default_factory=dict)

    @property
    def incremental(self) -> bool:
        return bool(self.base)


def _facts(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {})


async def previous_pass(db: AsyncSession, run: WorkflowRun) -> tuple[str, dict[str, Any]]:
    """``(run id, facts)`` of the newest earlier run of this pull request that posted a review; ``('', {})``."""
    pr_id = str(_facts(run).get("pr_id") or "")
    if not pr_id:
        return "", {}
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.project_id == run.project_id, WorkflowRun.workflow_key == WORKFLOW_KEY,
        WorkflowRun.repository == run.repository, WorkflowRun.id != run.id,
    ).order_by(WorkflowRun.created_at.desc()).limit(_RECENT_RUNS))).scalars().all()
    for row in rows:
        facts = _facts(row)
        if str(facts.get("pr_id")) == pr_id and facts.get("posted") and facts.get("reviewed_sha"):
            return row.id, facts
    return "", {}


async def delta_base(root: str, previous_run: str, previous: dict[str, Any], *, head: str, merge_base: str,
                     target: str) -> Delta:
    """Whether this pass can review ``previous reviewed_sha..head`` only (see the module docstring)."""
    def full(reason: str) -> Delta:
        return Delta(full_because=reason, previous_run=previous_run, previous=previous)

    old = str(previous.get("reviewed_sha") or "")
    if not old:
        return Delta(full_because="first pass")
    if same_head(old, head):
        return full("the head was reviewed before")
    if str(previous.get("target_branch") or "") != target:
        return full("the target branch changed")
    if not previous.get("merge_base") or str(previous.get("merge_base")) != merge_base:
        return full("the target branch was merged into the pull request or moved its merge base")
    code, _out, _err = await safe_git.git(root, "merge-base", "--is-ancestor", old, head)
    if code != 0:
        return full("the history was rewritten (force push or rebase)")
    code, _out, _err = await safe_git.git(root, "diff", "--no-ext-diff", "--quiet", old, head)
    if code == 0:
        return full("no change since the last pass")
    return Delta(base=old, previous_run=previous_run, previous=previous)


def seed(previous: dict[str, Any]) -> dict[str, Any] | None:
    """The review node's previous verdict for a follow-up (``convergence.previous_findings``): the open findings of
    the last pass. ``None`` when nothing was open (the delta then gets a first-round review)."""
    open_findings = [dict(item) for item in previous.get("open_findings") or [] if isinstance(item, dict)]
    if not open_findings:
        return None
    return {"verdict": "changes", "summary": "", "node_id": REVIEW_NODE,
            "findings": [{key: item[key] for key in ("id", "severity", "file", "line", "fix", "replies") if key in item}
                         for item in open_findings]}


def reviewer_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The findings a later pass answers: the reviewer's own, never the recomputed deterministic ones."""
    return [{**{key: value for key, value in item.items() if key not in ("suggestion", "start_line")},
             **({"suggested": True} if str(item.get("suggestion") or "").strip() else {})}
            for item in findings if item.get("source") not in _DETERMINISTIC]


@dataclass(frozen=True, slots=True)
class Effective:
    review: dict[str, Any]
    fixed: list[dict[str, Any]]
    still_open: int
    new: int
    #: Open findings the follow-up withdrew after a person's answer in their thread (``convergence.WITHDRAWN``).
    withdrawn: list[dict[str, Any]] = field(default_factory=list)


def effective(record: dict[str, Any], previous: dict[str, Any]) -> Effective:
    """The pass as the pull request shows it, from the follow-up's record (``convergence.Settled.record``). Pure.

    Carried findings (open before) are marked ``carried`` (the summary lists them, they get no new inline comment);
    a new one below high is ``nonblocking``. The verdict follows the blocking findings that remain."""
    before = {str(item.get("id")): dict(item) for item in previous.get("open_findings") or []
              if isinstance(item, dict) and item.get("id")}
    findings = [dict(item) for item in record.get("findings") or [] if isinstance(item, dict)]
    fixed: list[dict[str, Any]] = []
    withdrawn: list[dict[str, Any]] = []
    numbers = [int(match.group(1)) for ident in [*before, *(str(item.get("id")) for item in findings)]
               if (match := _ID.match(ident))]
    number = max(numbers or [0])
    for item in record.get("dropped") or []:
        item = dict(item)
        reason = item.pop("dropped", "")
        if reason == "fixed":
            fixed.append(item)
        elif reason == "withdrawn" and str(item.get("id")) in before:
            withdrawn.append(item)
        elif reason == "out_of_scope" and str(item.get("id")) in before:
            findings.append(item)  # an open finding on a file the delta did not touch: nothing fixed it
        elif reason == "new_not_high":
            number += 1
            findings.append({**item, "id": f"F{number}", "nonblocking": True})
    for carried, items in ((True, findings), (False, fixed), (False, withdrawn)):
        for item in items:
            earlier = before.get(str(item.get("id")))
            if earlier is None:
                continue
            # The thread it was posted in and how it was answered; it did not block when it was new, and a later
            # push does not change that.
            item.update({key: earlier[key] for key in _CARRIED if earlier.get(key)})
            if carried:
                item["carried"] = True
    blocking = [item for item in findings if item.get("severity") in ("high", "medium")
                and not item.get("nonblocking")]
    review = {**record, "findings": findings, "verdict": "changes" if blocking else "pass"}
    review.pop("dropped", None)
    for carried in ("walkthrough", "acceptance"):  # a follow-up answer writes neither: the last pass's stay
        if not review.get(carried) and previous.get(carried):
            review[carried] = list(previous[carried])
    carried = sum(1 for item in findings if item.get("carried"))
    return Effective(review, fixed, carried, len(findings) - carried, withdrawn)


def thread_answers(passed: Effective, sha: str) -> list[dict[str, Any]]:
    """The replies of this pass in the threads of earlier inline comments: a fixed finding gets "Fixed in"
    and its thread resolved; a finding the follow-up found not fixed gets one reply with the reviewer's evidence (once
    per finding, never on every push)."""
    evidence = {str(item.get("id")): str(item.get("evidence") or "").strip()
                for item in passed.review.get("follow_up") or [] if isinstance(item, dict)}
    answers = [{"comment_id": str(item["comment_id"]), "reply": f"✅ Fixed in `{sha[:7]}`."
                + (f" {evidence[str(item.get('id'))]}" if evidence.get(str(item.get("id"))) else ""),
                "resolve": True, "id": item.get("id")} for item in passed.fixed if item.get("comment_id")]
    answers += [{"comment_id": str(item["comment_id"]), "resolve": True, "id": item.get("id"),
                 "reply": "↩️ Withdrawn after the answer in this thread."
                 + (f" {evidence[str(item.get('id'))]}" if evidence.get(str(item.get("id"))) else "")}
                for item in passed.withdrawn if item.get("comment_id")]
    partly = {str(item.get("id")): item for item in passed.review.get("follow_up") or []
              if isinstance(item, dict) and item.get("status") == "partly_fixed"}
    for item in passed.review.get("findings") or []:
        said, part = evidence.get(str(item.get("id"))), partly.get(str(item.get("id")))
        if item.get("carried") and item.get("comment_id") and part is not None:  # progress is news on every pass
            answers.append({"comment_id": str(item["comment_id"]), "resolve": False, "id": item.get("id"),
                            "reply": f"◐ Partly fixed in `{sha[:7]}`." + (f" {said}" if said else "")
                            + f" Still open: {part.get('remaining')}"})
        elif item.get("carried") and item.get("comment_id") and not item.get("answered") and said is not None:
            answers.append({"comment_id": str(item["comment_id"]), "resolve": False, "id": item.get("id"),
                            "reply": f"Still open after `{sha[:7]}`." + (f" {said}" if said else "")})
    return answers


async def superseded_by(db: AsyncSession, run: WorkflowRun) -> str:
    """The id of a newer run of this pull request for another head (a push since this run started); ``''``."""
    pr_id, head = str(_facts(run).get("pr_id") or ""), str(_facts(run).get("reviewed_sha") or "")
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.project_id == run.project_id, WorkflowRun.workflow_key == WORKFLOW_KEY,
        WorkflowRun.repository == run.repository, WorkflowRun.id != run.id,
        WorkflowRun.created_at > run.created_at,
    ).order_by(WorkflowRun.created_at.desc()).limit(_RECENT_RUNS))).scalars().all()
    for row in rows:
        facts = _facts(row)
        newer = str(facts.get("head_sha") or facts.get("reviewed_sha") or "")
        if str(facts.get("pr_id")) == pr_id and newer and not same_head(newer, head):
            return row.id
    return ""


def blocking_ids(review: dict[str, Any]) -> list[str]:
    """The ids of the findings that made the status ``failure`` (``@octryx ignore`` turns it once none is left)."""
    return [str(item.get("id") or item.get("source") or "?") for item in review.get("findings") or []
            if item.get("severity") in ("high", "medium") and not item.get("nonblocking")]


def incremental_pass(review: dict[str, Any], facts: dict[str, Any]) -> Effective | None:
    """The incremental pass's effective review (:func:`effective`); ``None`` on a full pass."""
    if not dict(facts.get("incremental") or {}).get("from") or not review.get("verdict"):
        return None
    return effective(review, dict(facts.get("previous_pass") or {}))


__all__ = ["Delta", "Effective", "REVIEW_NODE", "delta_base", "effective", "previous_pass", "reviewer_findings",
           "seed", "superseded_by", "thread_answers", "blocking_ids", "incremental_pass"]
