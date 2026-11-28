"""``@octryx ignore [reason]`` (stage D1b): a finding closed on its pull request, and a team rule proposed."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...models import Project, WorkflowRun
from ...models.runtime.code_intelligence import CodeRepository
from .comment_events import CommentEvent
from .starter import CONTEXT_KEY, WORKFLOW_KEY

NEAR_LINES = 3


async def last_posted(db: AsyncSession, project_id: str, repository: str, pr_id: str) -> WorkflowRun | None:
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.project_id == project_id, WorkflowRun.workflow_key == WORKFLOW_KEY,
        WorkflowRun.repository == repository).order_by(WorkflowRun.created_at.desc()).limit(200))).scalars().all()
    return next((row for row in rows if str(dict(dict(row.context or {}).get(CONTEXT_KEY) or {}).get("pr_id")) ==
                 str(pr_id) and dict(dict(row.context or {}).get(CONTEXT_KEY) or {}).get("posted")), None)


def without_ignored(findings: list[dict[str, Any]], ignored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def closed(item: dict[str, Any]) -> bool:
        if item.get("source") in ("caller_check", "ci"):
            return False
        for gone in ignored:
            if item.get("carried") and item.get("id") == gone.get("id"):
                return True
            if item.get("file") == gone.get("file") and type(item.get("line")) is int and type(
                    gone.get("line")) is int and abs(item["line"] - gone["line"]) <= NEAR_LINES:
                return True
        return False

    return [item for item in findings if not closed(item)]


async def ignore_finding(db: AsyncSession, project_id: str, record: CodeRepository, event: CommentEvent,
                         reason: str, user_id: str, who: str, send: Any) -> str:
    from .rule_proposals import propose

    run = await last_posted(db, project_id, event.repository, event.pr_id)
    facts = dict(dict(run.context or {}).get(CONTEXT_KEY) or {}) if run is not None else {}
    finding = next((item for item in facts.get("open_findings") or [] if event.inline
                    and str(item.get("comment_id") or "") == event.thread_root), None)
    if run is None or finding is None:
        await send({"comment": "Octryx: write `ignore` (after the mention) as a reply in the thread of one of its "
                               "findings."} if not event.inline else {"thread_answers": [{
                                   "comment_id": event.thread_root, "resolve": False,
                                   "reply": "Octryx: this thread carries no open finding of its last review."}]})
        return "no_finding"
    ignored = [*(facts.get("ignored") or []), {**{key: finding.get(key) for key in (
        "id", "severity", "file", "line", "fix")}, "by": user_id, "reason": reason}]
    open_findings = [item for item in facts.get("open_findings") or [] if item.get("id") != finding.get("id")]
    posted = dict(facts.get("posted") or {})
    blocking = [ident for ident in posted.get("blocking") or [] if ident not in {item["id"] for item in ignored}]
    project = await db.get(Project, project_id)
    proposal = propose(project, repository_id=record.id, finding=finding, reason=reason, proposed_by=user_id,
                       pr_url=str(facts.get("url") or "")) if project is not None else {}
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {
        **facts, "open_findings": open_findings, "ignored": ignored, "posted": {**posted, "blocking": blocking}}}
    flag_modified(run, "context")
    await db.commit()
    from .outcomes import count_ignored

    count_ignored(event.provider, event.repository, finding)  # F3
    because = f": {reason}" if reason else ""
    await send({"thread_answers": [{"comment_id": event.thread_root, "resolve": True, "reply": (
        f"🙈 Ignored by {who}{because}. Proposed to the Workspace admins as a team rule"
        + (f" (proposal `{proposal['id']}`)." if proposal else "."))}]})
    if "blocking" in posted and posted.get("state") == "failure" and not blocking:
        await send({"commit_status": {"state": "success", "target_url": str(facts.get("url") or ""),
                                      "description": f"No blocking findings ({len(ignored)} ignored)"}},
                   commit=str(facts.get("reviewed_sha") or ""))
    return "ignored"


__all__ = ["NEAR_LINES", "ignore_finding", "last_posted", "without_ignored"]
