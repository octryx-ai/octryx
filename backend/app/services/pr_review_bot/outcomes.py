"""What became of the bot's findings, counted when it happens
(``review_bot_metrics.count_outcome``; metrics are emitted at the event, never queried):

- ``fixed`` / ``suggestion_applied``: an incremental pass found an open finding fixed; ``suggestion_applied`` when it
  carried a suggestion and a commit of the delta is GitHub's "Apply suggestion…" commit;
- ``ignored``: ``@octryx ignore`` (``ignore``);
- ``open_at_close``: the sync no longer lists the pull request as open while its last pass still had open findings
  (counted once per pull request, marked on that run).

The bot's precision is (fixed + suggestion_applied) / (fixed + suggestion_applied + ignored).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...models import WorkflowRun
from ..observability.review_bot_metrics import count_outcome
from ..workflow_runs import safe_git
from .starter import CONTEXT_KEY, WORKFLOW_KEY

_APPLIED = re.compile(r"^apply suggestions?\b", re.IGNORECASE)


async def suggestion_commits(root: str, base: str, head: str) -> bool:
    """Whether the delta holds a commit GitHub made by applying a review suggestion."""
    if not root or not base or not head:
        return False
    code, out, _err = await safe_git.git(root, "log", "--format=%s", f"{base}..{head}")
    return code == 0 and any(_APPLIED.search(line.strip()) for line in out.splitlines())


async def count_pass(run: WorkflowRun, provider: str, fixed: list[dict[str, Any]], root: str, base: str,
                     head: str) -> None:
    applied = await suggestion_commits(root, base, head) if any(item.get("suggested") for item in fixed) else False
    for item in fixed:
        outcome = "suggestion_applied" if applied and item.get("suggested") else "fixed"
        count_outcome(provider, str(run.repository or ""), str(item.get("severity") or ""), outcome)


def count_ignored(provider: str, repository: str, finding: dict[str, Any]) -> None:
    count_outcome(provider, repository, str(finding.get("severity") or ""), "ignored")


async def count_closed(db: AsyncSession, project_id: str, repository: str, open_numbers: set[str]) -> int:
    """``open_at_close`` for every pull request whose last posted pass still had open findings and that the sync no
    longer lists as open; each counted once. How many findings were counted."""
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.project_id == project_id, WorkflowRun.workflow_key == WORKFLOW_KEY,
        WorkflowRun.repository == repository).order_by(WorkflowRun.created_at.desc()).limit(500))).scalars().all()
    latest: dict[str, WorkflowRun] = {}
    for row in rows:
        facts = dict(dict(row.context or {}).get(CONTEXT_KEY) or {})
        pr_id = str(facts.get("pr_id") or "")
        if pr_id and facts.get("posted") and pr_id not in latest:
            latest[pr_id] = row
    counted = 0
    for pr_id, row in latest.items():
        facts = dict(dict(row.context or {}).get(CONTEXT_KEY) or {})
        if pr_id in open_numbers or facts.get("closed_counted"):
            continue
        for item in facts.get("open_findings") or []:
            count_outcome(repository.partition(":")[0], repository, str(dict(item).get("severity") or ""),
                          "open_at_close")
            counted += 1
        row.context = {**dict(row.context or {}), CONTEXT_KEY: {**facts, "closed_counted": True}}
        flag_modified(row, "context")
    return counted


__all__ = ["count_closed", "count_ignored", "count_pass", "suggestion_commits"]
