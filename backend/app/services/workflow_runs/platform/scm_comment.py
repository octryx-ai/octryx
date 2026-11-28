"""``scm.comment``: post a run text (a review verdict and its findings, ...) on the run's pull request."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from .dispatch import FAILED, ToolOutcome, dispatch_tool
from .repo_ref import _no_repository, parse_repository
from .texts import run_text


async def comment(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    ref = parse_repository(run.repository)
    if ref is None:
        return _no_repository(run)
    if ref.provider != "bitbucket":
        return ToolOutcome(FAILED, reason=f"a pull request comment is not available for {ref.provider} yet")
    pr = dict(run.pull_request or {})
    target = {"pr_id": pr["id"]} if pr.get("id") else {"from_branch": run.branch} if run.branch else None
    if target is None:
        return ToolOutcome(FAILED, reason="the run has no pull request and no branch to comment on")
    body = await run_text(db, run, str(params.get("text_from") or "findings"))
    if not body:
        return ToolOutcome(FAILED, reason="nothing to comment")
    return await dispatch_tool(db, run, "add_bitbucket_pull_request_comment", {**ref.args(), **target, "text": body},
                               capability_class="deliver")


__all__ = ["comment"]
