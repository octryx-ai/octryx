"""A run's pull request details: its target, description notes and findings, and what the run records once opened."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun
from . import pr_work_state
from .dispatch import CLASS_NOT_CONFIGURED, FAILED, ToolOutcome
from .pr_reviewers import (
    REQUESTER_IS_AUTHOR,
    REQUESTER_UNRESOLVED,
    PrReviewers,
    author_note,
    record_reviewer_skipped,
    requester_mention,
    stand_in,
    stand_in_note,
    unresolved_note,
)
from .repo_ref import RepoRef

logger = logging.getLogger(__name__)


def _no_pr_target(run: WorkflowRun, outcome: ToolOutcome) -> ToolOutcome:
    reason = (f"the repository had no commits when the run started, so the run's branch '{run.branch}' is its first "
              "branch and there is no target branch to open a pull request into. Create the repository's default "
              "branch (for example from this branch) in the source control system, then retry this step"
              f" (the provider answered: {outcome.reason[:200]})")
    return ToolOutcome(FAILED, outcome.result, reason, failure_class=CLASS_NOT_CONFIGURED)


async def _pr_target(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> tuple[str, str]:
    explicit = str(params.get("target_branch") or "").strip()
    base = str(dict(run.context or {}).get("base_branch") or "").strip()
    if explicit or not base:
        return explicit, ""
    from ..epic_chain import CHAIN_KEY

    after_id = str(dict(dict(run.context or {}).get(CHAIN_KEY) or {}).get("after_run") or "")
    after = await db.get(WorkflowRun, after_id) if after_id else None
    earlier = dict(after.pull_request or {}) if after is not None else {}
    if earlier.get("id") and earlier.get("branch") == base:
        link = f" ({earlier['url']})" if earlier.get("url") else ""
        return base, (f"Stacks on pull request #{earlier['id']}{link} from {base}: merge that one first, then this "
                      "one (the change shown here is only this story's).")
    return base, f"Stacks on the branch {base}: merge its pull request first, then this one."


def _finding_lines(items: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in items:
        where = str(item.get("file") or "").strip()
        where = f" ({where}:{item['line']})" if where and item.get("line") else (f" ({where})" if where else "")
        text = " ".join(str(item.get("fix") or item.get("summary") or item.get("reason") or "").split())
        lines.append(f"- {str(item.get('severity') or 'note').lower()}{where}: {text}".rstrip(": "))
    return lines


def review_notes_text(run: WorkflowRun) -> str:
    from ..auto_accept import REVIEW_NOTES_KEY

    notes = [dict(item) for item in dict(run.context or {}).get(REVIEW_NOTES_KEY) or [] if isinstance(item, dict)]
    lines = _finding_lines(notes)
    if not lines:
        return ""
    return "Review notes (medium and low findings of the independent review, not revised):\n" + "\n".join(lines)


OPEN_FINDINGS_TITLE = "Open review findings — decide before merging"


def open_findings_text(run: WorkflowRun) -> str:
    from ..auto_accept import OPEN_FINDINGS_KEY

    items = [dict(item) for item in dict(run.context or {}).get(OPEN_FINDINGS_KEY) or [] if isinstance(item, dict)]
    lines = _finding_lines(items)
    if not lines:
        return ""
    return (f"## {OPEN_FINDINGS_TITLE}\n\nThe independent review still reports these after the automatic revisions; "
            "the run continued so you can decide them here.\n" + "\n".join(lines))


# GitHub refuses a pull request body over 65,536 characters (422); review notes and open findings have no bound.
MAX_PR_DESCRIPTION = 60_000


# The links block is the tail: never cut, so a shortened description still leads back to the run, session and plan.
def _bounded_description(text: str, run: WorkflowRun, links: str = "") -> str:
    tail = f"\n\n{links}" if links else ""
    if len(text) + len(tail) <= MAX_PR_DESCRIPTION:
        return text + tail
    note = f"\n\n(Shortened: the whole list is on the platform's page of workflow run {run.id}.)"
    return text[:MAX_PR_DESCRIPTION - len(note) - len(tail)].rstrip() + note + tail


async def run_links(db: AsyncSession, run: WorkflowRun) -> str:
    from ..pr_links import links_block
    from ..records import main_session_id

    return await links_block(db, run=run, session_id=await main_session_id(db, run))


async def _pr_description(db: AsyncSession, run: WorkflowRun, chosen: PrReviewers, description: str
                          ) -> tuple[PrReviewers, str]:
    if chosen.is_author:
        description = author_note(description, await requester_mention(db, run))
    elif chosen.unresolved:
        identity, name = await stand_in(db, run, chosen.platform)
        if identity:
            chosen = replace(chosen, owners=tuple(dict.fromkeys([identity, *chosen.owners])))
            description = stand_in_note(description, await requester_mention(db, run), chosen.platform, name)
        else:
            description = unresolved_note(description, await requester_mention(db, run), chosen.platform)
    return chosen, description


async def _record_opened(db: AsyncSession, run: WorkflowRun, ref: RepoRef, chosen: PrReviewers, outcome: ToolOutcome,
                         item: Any, title: str) -> None:
    from ...secure_work.pull_requests.pull_requests import sync_pull_request
    from ...secure_work.pull_requests.record_identity import answered_pull_request, pull_request_identity
    from ..records import main_session_id

    skipped = str(outcome.result.get("reviewer_skipped") or "") or (REQUESTER_IS_AUTHOR if chosen.is_author else "")
    why = chosen.unresolved
    if not skipped and chosen.requester and chosen.requester in list(outcome.result.get("reviewers_unresolved") or []):
        why = f"{ref.provider} does not know the requester's linked account '{chosen.requester}'"
    if why and not skipped:
        skipped = REQUESTER_UNRESOLVED  # opened without them: they review and merge it themselves
    reviewers = [name for name in chosen.names if name != chosen.requester] if skipped else chosen.names
    number, url = answered_pull_request(outcome.result)
    identity = pull_request_identity(ref.provider, url, ref.path, number) if number and url else None
    run.pull_request = {"provider": ref.provider, "repository": ref.path, "id": number, "url": url,
                        "branch": run.branch, "reviewers": reviewers, "state": "open",
                        **({"identity": identity} if identity else {}),
                        **({"reviewer_skipped": skipped, "requester_platform": chosen.platform} if skipped else {})}
    if skipped:
        record_reviewer_skipped(db, run, skipped, detail=why if skipped == REQUESTER_UNRESOLVED else "")
    if item is not None and identity:
        user = await db.get(User, run.requested_by)
        await sync_pull_request(db, current_user=user, workspace_id=run.project_id, payload={
            "work_item_id": item.id, "identity": identity,
            "pr_url": url, "title": title, "source_branch": run.branch, "status": "open", "reviewers": reviewers,
            "run_id": run.id, "session_id": await main_session_id(db, run),
        })
        try:
            await pr_work_state.pull_request_opened(db, run, item, user)
        except Exception:  # noqa: BLE001 - the pull request exists; a Jira hiccup must not fail the step
            logger.warning("pull_request_opened work state failed run_id=%s", run.id, exc_info=True)
            from ..records import record_event

            record_event(db, run, "work_state_failed", node_id=run.current_node_id,
                         detail={"on": "pull_request_opened", "pull_request": number})
