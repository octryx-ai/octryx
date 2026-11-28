"""Anti-slop D: a pull request links back to the run and session that opened it and the plan they followed, and the
session, its handoffs and its run list the pull requests back. Links are URLs and ids only."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, WorkflowRun, WorkflowRunSession, WorkPullRequest
from ...models.runtime.secure_work import WorkChangePlan

LINKS_TITLE = "Octryx links"
MAX_LISTED = 20
_SHOWN_PARTS, _SHOWN_PATHS, _PART_CHARS = 3, 5, 80


def _origin() -> str:
    from ..knowledge.episodes.policy import public_origin

    return public_origin() or ""


def run_url(run_id: str) -> str:
    origin = _origin()
    return f"{origin}/api/v1/workflow-runs/{run_id}" if origin else f"workflow run {run_id}"


def session_url(session_id: str) -> str:
    origin = _origin()
    return f"{origin}/chat?session_id={session_id}" if origin else f"session {session_id}"


async def approved_plan(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    from .confirmation_payloads import plan_hash as work_plan_hash
    from .plan_scope import plan_hash, scope_state
    from .platform.work_plan import DRAFTED_PLAN_KEY

    state = scope_state(run)
    if state["approved"]:
        plan = state["plan"]
        return {"source": "change_plan", "hash": plan_hash(plan), "parts": list(plan.get("parts") or []),
                "paths": list(plan.get("paths") or [])}
    drafted = dict(dict(run.context or {}).get(DRAFTED_PLAN_KEY) or {})
    row = await db.get(WorkChangePlan, str(drafted["id"])) if drafted.get("id") else None
    if row is None or row.status != "approved" or row.work_item_id != run.work_item_id:
        return None
    return {"source": "work_change_plan", "id": row.id, "title": row.title, "version": row.version,
            "hash": work_plan_hash(row), "status": row.status}


def _listed(values: list[str], shown: int, separator: str) -> str:
    more = f" (+{len(values) - shown} more)" if len(values) > shown else ""
    return separator.join(value[:_PART_CHARS] for value in values[:shown]) + more


def plan_line(plan: dict[str, Any]) -> str:
    if plan["source"] == "change_plan":
        parts, paths = plan["parts"], plan["paths"]
        return (f"Approved plan ({plan['hash']}): {len(parts)} part(s): {_listed(parts, _SHOWN_PARTS, '; ')}"
                f" · paths: {_listed(paths, _SHOWN_PATHS, ', ')}")
    return f"Approved plan: {plan['title'][:_PART_CHARS]} v{plan['version']} ({plan['hash']})"


async def links_block(db: AsyncSession, *, run: WorkflowRun | None, session_id: str | None) -> str:
    lines = [f"- Run: {run_url(run.id)}"] if run is not None else []
    if session_id:
        lines.append(f"- Session: {session_url(session_id)}")
    plan = await approved_plan(db, run) if run is not None else None
    if plan is not None:
        lines.append(f"- {plan_line(plan)}")
    return f"{LINKS_TITLE}\n" + "\n".join(lines) if lines else ""


async def with_session_links(params: dict[str, Any], context: Any) -> dict[str, Any]:
    from .records import active_run_for_session

    db, session_id = getattr(context, "db", None), str(getattr(context, "session_id", None) or "")
    if db is None or not session_id or await db.get(Session, session_id) is None:
        return params
    text = str(params.get("description") or "")
    # A run's own pull request already carries the block (pr_details); a replayed call carries it too.
    if session_url(session_id) in text:
        return params
    block = await links_block(db, run=await active_run_for_session(db, session_id), session_id=session_id)
    return {**params, "description": f"{text.rstrip()}\n\n{block}" if text.strip() else block}


def _pull_request_view(url: str, title: str, state: str, run_id: str | None) -> dict[str, Any]:
    return {"url": url, "title": title, "state": state, "run_id": run_id}


async def session_pull_requests(db: AsyncSession, session_id: str) -> list[dict[str, Any]]:
    from .states import ROLE_MAIN

    # Read through the Workspace filter: a session hidden from the viewer lists nothing, wherever its PRs live.
    if (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none() is None:
        return []
    rows = (await db.execute(
        select(WorkPullRequest).where(WorkPullRequest.session_id == session_id)
        .order_by(WorkPullRequest.created_at.desc()).limit(MAX_LISTED)
    )).scalars().all()
    listed = [_pull_request_view(row.pr_url, row.title or "", row.status, row.run_id) for row in rows]
    runs = (await db.execute(
        select(WorkflowRun).join(WorkflowRunSession, WorkflowRunSession.run_id == WorkflowRun.id)
        .where(WorkflowRunSession.session_id == session_id, WorkflowRunSession.role == ROLE_MAIN)
        .order_by(WorkflowRun.created_at.desc()).limit(MAX_LISTED)
    )).scalars().all()
    known = {entry["url"] for entry in listed}
    for run in runs:
        recorded = dict(run.pull_request or {})
        if recorded.get("url") and recorded["url"] not in known:
            known.add(recorded["url"])
            listed.append(_pull_request_view(str(recorded["url"]), run.title or "", str(recorded.get("state") or ""),
                                             run.id))
    return listed[:MAX_LISTED]


async def item_pull_requests(db: AsyncSession, work_item_id: str) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(WorkPullRequest).where(WorkPullRequest.work_item_id == work_item_id)
        .order_by(WorkPullRequest.created_at.desc()).limit(MAX_LISTED)
    )).scalars().all()
    return [{"url": row.pr_url, "state": row.status, "session_id": row.session_id, "run_id": row.run_id}
            for row in rows]


async def item_plan(db: AsyncSession, work_item_id: str) -> dict[str, Any] | None:
    from .confirmation_payloads import plan_hash

    row = (await db.execute(
        select(WorkChangePlan).where(WorkChangePlan.work_item_id == work_item_id, WorkChangePlan.status == "approved")
        .order_by(WorkChangePlan.version.desc()).limit(1)
    )).scalar_one_or_none()
    return ({"source": "work_change_plan", "id": row.id, "version": row.version, "hash": plan_hash(row),
             "status": row.status} if row is not None else None)
