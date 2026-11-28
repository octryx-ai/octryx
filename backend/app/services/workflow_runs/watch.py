"""A run that waits for an external state: the server observes it, never the agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...models.runtime.secure_work import WorkItem
from ...time_utils import utc_now
from .graph import PhasedNode, graph_for_run
from .pause import payload_hash
from .records import WorkflowRunError, lock_run, record_event
from .states import STATUS_WAITING, WAITING_CONFIRMATION, WAITING_WATCH
from .watch_events import (
    APPROVAL_DECIDED,
    CI_FAILED,
    CI_SUCCEEDED,
    JIRA_STATUS,
    PR_APPROVED,
    PR_DECLINED,
    PR_MERGED,
    WatchEvent,
)

logger = logging.getLogger(__name__)

ADVANCE_AUTO = "auto"
EVENT_WATCH_MET = "watch_condition_met"
POLL_INTERVAL_SECONDS = 300


def ci_params(run: WorkflowRun, params: dict[str, Any]) -> dict[str, Any]:
    if params.get("target") != "deploy":
        return params
    deploy = dict(dict(run.context or {}).get("deploy") or {})
    return {"job": deploy.get("job"), "queue_url": deploy.get("queue_url"), "unpinned": True, "deploy": True,
            "build_number": deploy.get("build_number")}


def watch_target(run: WorkflowRun, node: PhasedNode) -> dict[str, Any]:
    from ..secure_work.pull_requests.record_identity import stored_identity

    params = ci_params(run, dict(node.config.get("params") or {}))
    return {
        "pr": stored_identity(run.pull_request),
        "repository": run.repository, "branch": run.branch, "ticket_key": run.ticket_key,
        "work_state": params.get("work_state"), "job": params.get("job"), "workflow": params.get("workflow"),
        "head_sha": None if params.get("unpinned") else dict(run.context or {}).get("head_sha"),
        "approval_id": dict(run.context or {}).get("last_approval_id"),
        "deploy": bool(params.get("deploy")), "build_number": params.get("build_number"),
    }


def _same(left: Any, right: Any) -> bool:
    return bool(left) and str(left).strip().lower() == str(right or "").strip().lower()


def event_pull_request(event: WatchEvent, number: str | None = None) -> dict[str, str]:
    # The host comes from the signed payload: an event without it names no pull request.
    from ..secure_work.pull_requests.record_identity import identity_of, web_host

    return identity_of(event.provider, web_host(event.pr_url), event.repository,
                       event.pr_id if number is None else number)


def matches(event: WatchEvent, target: dict[str, Any]) -> bool:
    if event.condition in (PR_APPROVED, PR_MERGED, PR_DECLINED):
        from ..secure_work.pull_requests.record_identity import same_pull_request

        return same_pull_request(event_pull_request(event), target.get("pr"))
    if event.condition in (CI_SUCCEEDED, CI_FAILED):
        return _ci_matches(event, target)
    if event.condition == JIRA_STATUS:
        return _same(event.ticket_key, target.get("ticket_key")) and _same(event.work_state, target.get("work_state"))
    if event.condition == APPROVAL_DECIDED:
        return _same(event.approval_id, target.get("approval_id"))
    return False


def _ci_matches(event: WatchEvent, target: dict[str, Any]) -> bool:
    # One workflow's success is not the commit's; a deploy counts only its own build.
    if target.get("deploy"):
        return (bool(event.job) and _same(event.job, target.get("job")) and bool(target.get("build_number"))
                and _same(event.build_number, target.get("build_number")))
    head = str(target.get("head_sha") or "")
    if head and not _same(event.sha, head):
        return False  # another commit, or an event that does not say which commit it built
    if event.job:
        if not _same(event.job, target.get("job")):
            return False
    else:
        repository = str(target.get("repository") or "").partition(":")[2]
        if not (_same(event.repository, repository) and _same(event.branch, target.get("branch"))):
            return False
    if event.provider == "bitbucket":
        # One commit status of several (Pipelines and other reporters) proves nothing about the others: a failure
        # fails the commit; success is judged by the poll over all statuses of the commit.
        return event.condition == CI_FAILED
    if event.provider == "github":
        if target.get("workflow"):
            return _same(event.workflow, target.get("workflow"))
        # Without a named workflow a success event of one workflow proves nothing about the others: the poll
        # judges all workflows of the commit together. A failure of any workflow fails the commit.
        return event.condition == CI_FAILED
    return True


async def _watching_runs(db: AsyncSession, *, project_id: str | None = None) -> list[WorkflowRun]:
    query = select(WorkflowRun).where(WorkflowRun.status == STATUS_WAITING, WorkflowRun.waiting_kind == WAITING_WATCH)
    if project_id is not None:
        query = query.where(WorkflowRun.project_id == project_id)
    return list((await db.execute(query)).scalars().all())


async def _claimed(db: AsyncSession, run: WorkflowRun) -> WorkflowRun | None:
    try:
        run = await lock_run(db, run)
    except WorkflowRunError:
        return None
    return run if run.status == STATUS_WAITING and run.waiting_kind == WAITING_WATCH else None


async def record_condition(db: AsyncSession, run: WorkflowRun, condition: str, *, source: str,
                           detail: dict[str, Any] | None = None) -> bool:
    from .engine import resolve_current_node

    if run.status != STATUS_WAITING or run.waiting_kind != WAITING_WATCH:
        return False
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    if node is None or condition not in {str(item) for item in node.config.get("conditions") or []}:
        return False
    met = {"condition": condition, "source": source, "detail": dict(detail or {}), "at": utc_now().isoformat()}
    context = dict(run.context or {})
    context["watched"] = {**dict(context.get("watched") or {}), node.id: met}
    run.context = context
    record_event(db, run, EVENT_WATCH_MET, node_id=node.id, detail={"condition": condition, "source": source})
    if condition in (PR_MERGED, PR_DECLINED):  # the recorded PR is re-read from its host by the refresh worker
        from ..secure_work.pull_requests.refresh import request_refresh_for_run

        await request_refresh_for_run(db, run)
    if str(node.config.get("advance") or "") == ADVANCE_AUTO:
        await resolve_current_node(db, run, condition, actor_id=None)
        return True
    payload = {"subject": "advance", "watched": condition, "ticket_key": run.ticket_key, "branch": run.branch,
               "pull_request": dict(run.pull_request or {})}
    state = dict(run.node_state or {})
    run.waiting_kind = WAITING_CONFIRMATION
    run.node_state = {**state, "waiting": {**dict(state.get("waiting") or {}), "kind": WAITING_CONFIRMATION,
                                           "subject": "advance", "watched": condition, "payload": payload,
                                           "payload_hash": payload_hash(payload), "since": utc_now().isoformat(),
                                           "question": f"Observed: {condition}. Go on?"}}
    return True


def _target(run: WorkflowRun) -> dict[str, Any]:
    target = dict(dict(dict(run.node_state or {}).get("waiting") or {}).get("target") or {})
    if target.get("deploy"):
        target["build_number"] = dict(dict(run.context or {}).get("deploy") or {}).get("build_number")
    return target


async def deliver_event(
    db: AsyncSession, event: WatchEvent, *, source: str, project_id: str | None = None
) -> list[str]:
    # A webhook's event reaches only the runs of the webhook's Workspace.
    if event.condition == PR_MERGED and event.repository:
        # A merge refreshes the repository's code graph (mirror, index), whether a run waits or not.
        from ..code_intelligence.graph_refresh import on_pr_merged

        try:
            await on_pr_merged(db, event.repository, project_id)
        except Exception:  # noqa: BLE001 - the code graph never stops a run's watch
            logger.exception("code_graph.pr_merged_refresh_not_started")
    if event.condition == PR_MERGED and event.reverts:
        await record_revert(db, event, project_id=project_id)
    moved = []
    for run in await _watching_runs(db, project_id=project_id):
        if not matches(event, _target(run)) or (run := await _claimed(db, run)) is None:
            continue
        if matches(event, _target(run)) and await record_condition(db, run, event.condition, source=source,
                                                             detail=event.to_dict()):
            moved.append(run.id)
    return moved


EVENT_PR_REVERTED = "pr_reverted"
REVERT_LOOKBACK_DAYS = 90


async def record_revert(db: AsyncSession, event: WatchEvent, *, project_id: str | None = None) -> list[str]:
    from datetime import timedelta

    from ..secure_work.pull_requests.record_identity import same_pull_request, stored_identity

    query = select(WorkflowRun).where(WorkflowRun.created_at >= utc_now() - timedelta(days=REVERT_LOOKBACK_DAYS))
    if project_id:
        query = query.where(WorkflowRun.project_id == project_id)
    reverted = []
    reverted_pr = event_pull_request(event, event.reverts)
    for run in (await db.execute(query)).scalars():
        if same_pull_request(reverted_pr, stored_identity(run.pull_request)):
            record_event(db, run, EVENT_PR_REVERTED, node_id=None,
                         detail={"provider": event.provider, "repository": event.repository,
                                 "reverted_pr": event.reverts, "revert_pr": event.pr_id})
            reverted.append(run.id)
    return reverted


async def work_state_for_jira_status(
    db: AsyncSession, ticket_key: str, status: str, *, project_id: str | None = None
) -> str:
    from ..secure_work.lifecycle_transitions import default_workflow_for_item
    from ..secure_work.sync_policy import mapped_status

    query = select(WorkItem).where(WorkItem.source_key == ticket_key)
    if project_id is not None:
        query = query.where(WorkItem.project_id == project_id)
    item = (await db.execute(query)).scalars().first()
    workflow = await default_workflow_for_item(db, item) if item is not None else None
    for state, mapping in dict(getattr(workflow, "mappings_json", None) or {}).items():
        if isinstance(mapping, dict) and _same(mapped_status(mapping), status):
            return str(state)
    return ""


async def deliver_jira_change(db: AsyncSession, payload: dict[str, Any], *, project_id: str) -> list[str]:
    key, status = str(payload.get("key") or ""), str(payload.get("status") or "")
    if not key or not status:
        return []
    work_state = await work_state_for_jira_status(db, key, status, project_id=project_id)
    if not work_state:
        return []
    return await deliver_event(db, WatchEvent(JIRA_STATUS, ticket_key=key, work_state=work_state),
                               source="jira_change", project_id=project_id)


def pr_condition(provider: str, result: dict[str, Any]) -> str | None:
    state = str(result.get("state") or "").lower()
    if result.get("merged") is True or state == "merged":
        return PR_MERGED
    if state in ("closed", "declined"):
        return PR_DECLINED
    if provider == "bitbucket" and any(
            isinstance(item, dict) and item.get("approved") for item in result.get("reviewers") or []):
        return PR_APPROVED
    return None


async def _poll_run(db: AsyncSession, run: WorkflowRun) -> tuple[str | None, Any]:
    from ..secure_work.pull_requests.record_identity import stored_identity
    from .platform import ci
    from .platform.pr_adoption import read_recorded_pull_request

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    conditions = {str(item) for item in (node.config.get("conditions") if node else None) or []}
    identity = stored_identity(run.pull_request)
    if conditions & {PR_APPROVED, PR_MERGED, PR_DECLINED} and identity is not None:
        outcome = await read_recorded_pull_request(db, run, identity)
        condition = pr_condition(identity["provider"], outcome.result) if outcome is not None and outcome.ok else None
        if condition in conditions:
            return condition, None
    if conditions & {CI_SUCCEEDED, CI_FAILED}:
        result = await ci.read_ci_status(db, run, ci_params(run, dict(node.config.get("params") or {})) if node else {})
        condition = {"succeeded": CI_SUCCEEDED, "failed": CI_FAILED}.get(result.state)
        if condition is None and CI_SUCCEEDED in conditions and _no_ci_reported(run, result):
            # A repository without CI never reports a build, so the run would wait for ever. After
            # NO_CI_GRACE without any build for the pushed commit it goes on, and the result says why.
            unreadable = "cannot read GitHub Actions" in str(result.reason or "")
            result.reason = (f"no CI reported a build for this commit within {NO_CI_GRACE_MINUTES} minutes: "
                             + ("the connection cannot read GitHub Actions (grant it Actions read access to have CI "
                                "checked)" if unreadable else "the repository has no CI")
                             + "; the run goes on without it")
            return CI_SUCCEEDED, result
        return (condition if condition in conditions else None), result
    if JIRA_STATUS in conditions and run.work_item_id:
        item = await db.get(WorkItem, run.work_item_id)
        wanted = dict(node.config.get("params") or {}).get("work_state") if node else None
        if item is not None and wanted and _same(item.work_state, wanted):
            return JIRA_STATUS, None
    return None, None


NO_CI_GRACE_MINUTES = 10
_NO_BUILD_REASONS = ("no build status", "no Actions run", "no pipeline")


def _no_ci_reported(run: WorkflowRun, result: Any) -> bool:
    from datetime import datetime, timedelta

    from ...time_utils import utc_now

    # Bitbucket and GitLab answer "running ... yet" for a pushed commit nobody builds; a real build has no such reason.
    if str(getattr(result, "state", "")) not in ("unknown", "running") or not any(
            marker in str(getattr(result, "reason", "") or "") for marker in _NO_BUILD_REASONS):
        return False
    try:
        entered = datetime.fromisoformat(str(dict(run.node_state or {}).get("entered_at") or "")).replace(tzinfo=None)
    except ValueError:
        return False
    return utc_now().replace(tzinfo=None) - entered > timedelta(minutes=NO_CI_GRACE_MINUTES)


async def poll_watching_runs(db: AsyncSession) -> int:
    # Reads happen without the run claim and each run commits on its own, so no row stays locked across network calls.
    from .platform.ci import record_ci

    moved = 0
    for run_id in [run.id for run in await _watching_runs(db)]:
        run = await db.get(WorkflowRun, run_id)
        try:
            condition, ci_result = await _poll_run(db, run)
        except Exception:
            logger.warning("workflow_run.watch_poll_failed run_id=%s", run_id, exc_info=True)
            await db.rollback()
            continue
        if (condition or ci_result is not None) and (run := await _claimed(db, run)) is not None:
            if ci_result is not None:
                record_ci(run, ci_result)
            if condition and await record_condition(db, run, condition, source="poll"):
                moved += 1
        await db.commit()
    return moved


class WatchPollWorker:
    def __init__(self, session_factory, *, interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            try:
                async with self._session_factory() as db:
                    await poll_watching_runs(db)
            except Exception:
                logger.exception("Workflow run watch poll failed")


__all__ = ["ADVANCE_AUTO", "WatchPollWorker", "deliver_event", "deliver_jira_change", "event_pull_request", "matches",
           "pr_condition", "poll_watching_runs", "record_condition", "watch_target", "work_state_for_jira_status"]
