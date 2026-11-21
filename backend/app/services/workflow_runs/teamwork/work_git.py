"""The teamwork git work on the main thread: queued ops, the launcher turn that runs them and its report."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import utc_now
from ..records import record_event
from . import work_of
from .device_work_state import (
    EVENT_COMMIT_GUARDED,
    EVENT_SEQUENTIAL,
    FALLBACK_BRANCH_FAILED,
    PROVENANCE,
    _main_thread,
    _set_state,
    _state,
    _turn_of,
    item_branch,
)


def queue_op(run: WorkflowRun, op: str, key: str, *, sync: bool = False) -> None:
    """Queue ``op`` for ``key`` once (an op already queued or sent is not queued again). ``sync``: a ``branch`` op
    that merges the main folder's HEAD into the item's existing branch (its retry after a merge conflict)."""
    state = _state(run)
    entry = {"op": op, "key": key, "branch": item_branch(run, key), **({"sync": True} if sync else {})}
    sent = list(dict(state.get("sent") or {}).get("ops") or [])
    queued = list(state.get("ops") or [])
    if entry not in queued and entry not in sent:
        _set_state(run, {**state, "ops": [*queued, entry]})


def contract_view(run: WorkflowRun) -> dict[str, Any] | None:
    """The run contract's ``work_git``: the batch sent to the main thread and not reported yet."""
    sent = dict(_state(run).get("sent") or {})
    if not sent.get("ops"):
        return None
    return {"node_id": sent.get("node_id"), "entry": sent.get("entry"), "seq": sent.get("seq"), "ops": sent["ops"]}


async def flush(db: AsyncSession, run: WorkflowRun) -> str | None:
    """Send the queued ops with a main-thread turn when none is outstanding and the main thread is free."""
    from app.services.devices.job_state import ACTIVE_STATUSES

    from ...devices.chat_turn import DeviceTurnStarted, start_device_turn
    from ...devices.jobs import thread_job

    state = _state(run)
    if not state.get("ops") or state.get("sent"):
        return None
    thread, target = await _main_thread(db, run)
    busy = await thread_job(db, thread.id) if thread is not None else None
    if target is None or (busy is not None and busy.status in ACTIVE_STATUSES):
        return None  # the coordinator's turn (or another step) still runs: sent when it ends (``job_ended``)
    seq = int(state.get("seq") or 0) + 1
    started = await start_device_turn(
        db, user_id=thread.user_id, target=target, session_id=thread.id, fresh_session=True,
        prompt=f"Platform git work of run {run.id} (item worktrees and merges; the launcher runs it, no agent).",
        idempotency_key=f"{PROVENANCE}:git:{run.id}:{seq}"[:100])
    if not isinstance(started, DeviceTurnStarted):
        record_event(db, run, "teamwork_git_waiting", node_id=run.current_node_id, detail={"reason": started.reason})
        return None
    _set_state(run, {**state, "seq": seq, "ops": [], "sent": {
        "seq": seq, "ops": state["ops"], "job_id": started.job_id, "turn_id": await _turn_of(db, started.job_id),
        "node_id": run.current_node_id, "entry": dict(run.node_state or {}).get("entry"),
        "at": utc_now().isoformat()}})
    return started.job_id


def _record_change(run: WorkflowRun, change: Any, entry: Any) -> None:
    """The main folder against the run's base after a merge: the run's ``device_change`` (review, push)."""
    from ..octryx.facts import MAX_PATCH

    if not isinstance(change, dict):
        return
    context = dict(run.context or {})
    base = str(change.get("base") or "")
    patch = change.get("patch") if isinstance(change.get("patch"), str) else ""
    unavailable = bool(change.get("base_unavailable")) or base != str(context.get("base_sha") or "")
    context["device_change"] = {
        "node_id": run.current_node_id, "entry": entry, "base": base, "patch": "" if unavailable else patch[:MAX_PATCH],
        "truncated": change.get("truncated") is True or len(patch) > MAX_PATCH, "base_unavailable": unavailable,
        "at": utc_now().isoformat()}
    run.context = context


async def work_git_reported(db: AsyncSession, run: WorkflowRun, report: dict[str, Any]) -> str:
    """The launcher's report of a sent batch: branched items can start, merges reach the scheduler. ``recorded`` or
    ``stale`` (another batch, already reported)."""
    from .item_results import merge_reported
    from .scheduler import advance

    state = _state(run)
    sent = dict(state.get("sent") or {})
    if not sent or report.get("seq") != sent.get("seq"):
        return "stale"
    branched = dict(state.get("branched") or {})
    resync = set(state.get("resync") or [])
    merges: list[tuple[str, bool, list[str] | None, str | None]] = []
    fallback = state.get("fallback")
    for result in [item for item in report.get("results") or [] if isinstance(item, dict)]:
        key, outcome = str(result.get("key") or ""), str(result.get("state") or "")
        if result.get("kept_files"):
            # The launcher refused a work-plan commit's deletion of merged items' files and put them back.
            record_event(db, run, EVENT_COMMIT_GUARDED, node_id=run.current_node_id, detail={
                "op": str(result.get("op") or ""), "item": key,
                "files": [str(name)[:300] for name in result.get("kept_files") or []]})
        if result.get("op") == "branch" and outcome == "branched":
            conflicts = [str(name)[:300] for name in result.get("conflicts") or []]
            branched[key] = {"folder": str(result.get("folder") or ""), "branch": str(result.get("branch") or ""),
                             "head": str(result.get("head") or ""), "plan_version": work_of(run).get("plan_version"),
                             **({"conflicts": conflicts} if conflicts else {})}
            if key in resync:
                resync.discard(key)
                record_event(db, run, "teamwork_item_synced", node_id=run.current_node_id, detail={
                    "item": key, "conflicts": conflicts, "failed": str(result.get("sync_failed") or "")[:500] or None})
        elif result.get("op") == "branch":
            fallback = fallback or FALLBACK_BRANCH_FAILED
            record_event(db, run, EVENT_SEQUENTIAL, node_id=run.current_node_id,
                         detail={"reason": FALLBACK_BRANCH_FAILED, "item": key,
                                 "detail": str(result.get("detail") or "")[:500]})
        elif result.get("op") == "merge":
            merged = outcome == "merged"
            if merged or outcome == "conflict":
                # A conflicted item is branched again before its retry, with the story's work merged in: otherwise
                # it resumed its stale worktree with no branch
                # op and conflicted again until the loop limit.
                branched.pop(key, None)
            if outcome == "conflict":
                resync.add(key)
            files = [str(name)[:300] for name in result.get("files") or []] or None
            merges.append((key, merged, files, str(result.get("head") or "") or None))
    if "change" in report:
        _record_change(run, report["change"], sent.get("entry"))
    _set_state(run, {**state, "sent": None, "branched": branched, "resync": sorted(resync),
                     **({"fallback": fallback} if fallback else {})})
    for key, merged, files, sha in merges:
        await merge_reported(db, run, key=key, merged=merged, conflicts=None if merged else (files or []),
                             merged_sha=sha if merged else None)
    await flush(db, run)
    await advance(db, run)
    return "recorded"
