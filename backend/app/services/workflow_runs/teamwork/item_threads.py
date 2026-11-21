"""Start a teamwork item's turn on the device: its own chat thread, or the main thread in the sequential fallback."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun, WorkflowRunSession
from ....time_utils import utc_now
from ..graph import NODE_PHASE, PhasedNode
from ..records import RUN_METADATA_KEY
from . import ITEM_METADATA_KEY, ROLE_ITEM, RUNNING, item_marker, work_of
from .device_work_state import (
    PROVENANCE,
    _main_thread,
    _parallel_node,
    _set_state,
    _state,
    _turn_of,
    item_branch,
    item_folder,
)


def _role_node(node: PhasedNode, item: dict[str, Any]) -> PhasedNode:
    """The item's phase for the run settings (permission mode, governed model): its role template and model."""
    roles = dict(dict(node.config or {}).get("roles") or {})
    template = dict(roles.get(str(item.get("role") or "")) or {})
    model = str(item.get("model") or template.get("model") or "")
    return PhasedNode(id=node.id, kind=NODE_PHASE, title=str(item.get("title") or item["id"]),
                      config={**template, **({"model": model} if model else {})})


def _prompt(run: WorkflowRun, item: dict[str, Any], *, resumed: bool, conflicts: list[str] | None = None) -> str:
    from ..octryx.continuation_prompts import read_contract
    from ..run_texts import run_text

    merged = run_text("item.merged", files=", ".join(conflicts)) if conflicts else ""
    title = item.get("title") or item["id"]
    if resumed:
        return run_text("item.resumed", title=title, item_id=item["id"], run_id=run.id,
                        iteration=item.get("iteration") or 1,
                        why=str(item.get("reason") or run_text("item.reopened")), merged=merged,
                        read_contract=read_contract(run))
    return run_text("item.build", title=title, item_id=item["id"], workflow_key=run.workflow_key, run_id=run.id,
                    merged=merged, read_contract=read_contract(run))


async def _bound_prompt(db: AsyncSession, run: WorkflowRun, item: dict[str, Any], **kwargs: Any) -> str:
    """:func:`_prompt` with the run's catalog texts (its workflow's and Workspace's versions)."""
    from ..run_texts import run_texts

    async with run_texts(db, run):
        return _prompt(run, item, **kwargs)


async def _open_item_thread(db: AsyncSession, run: WorkflowRun, key: str, plan_version: Any) -> Session | None:
    """The open thread of ``key`` in this plan version, if one exists: the guard that an item never gets a second
    one, whatever its stored ``session_id`` says."""
    from sqlalchemy import select

    threads = (await db.execute(
        select(Session).join(WorkflowRunSession, WorkflowRunSession.session_id == Session.id)
        .where(WorkflowRunSession.run_id == run.id, WorkflowRunSession.role == ROLE_ITEM, Session.status == "active")
        .order_by(WorkflowRunSession.linked_at.desc()))).scalars()
    for thread in threads:
        marker = item_marker(thread) or {}
        if marker.get("key") == key and marker.get("plan_version") == plan_version:
            return thread
    return None


async def _item_thread(db: AsyncSession, run: WorkflowRun, item: dict[str, Any], main: Session,
                       target: dict[str, Any]) -> Session:
    """The item's own chat thread (reused when it already has one), bound to the run as role ``item``."""
    plan_version = work_of(run).get("plan_version")
    thread = await db.get(Session, str(item.get("session_id") or "")) if item.get("session_id") else None
    thread = thread or await _open_item_thread(db, run, item["id"], plan_version)
    marker = {"run_id": run.id, "node_id": str(work_of(run).get("node_id") or run.current_node_id),
              "key": item["id"], "iteration": int(item.get("iteration") or 1), "plan_version": plan_version}
    if thread is not None:
        thread.metadata_ = {**dict(thread.metadata_ or {}), ITEM_METADATA_KEY: marker,
                            "execution_target": {**target, "kind": "device"}}
        return thread
    thread = Session(user_id=main.user_id, project_id=run.project_id, status="active", origin="sub_agent",
                     parent_session_id=main.id, sub_agent_depth=1, metadata_={
                         "title": f"Item {item['id']}: {item.get('title') or ''}"[:200], "trigger": "sub_agent",
                         "execution_target": {**target, "kind": "device"}, ITEM_METADATA_KEY: marker,
                         RUN_METADATA_KEY: run.id})
    db.add(thread)
    await db.flush()
    # Never ``bind_session``: it would end the other items' bindings of the same role.
    db.add(WorkflowRunSession(run_id=run.id, session_id=thread.id, role=ROLE_ITEM, runtime="octryx_claude",
                              active=True))
    await db.flush()
    return thread


def _refusal(started: Any, session_id: str | None = None) -> dict[str, Any]:
    """The item's fields when its turn could not start: it stays ``pending`` with its thread (the next start reuses
    it). Device busy, offline or paused: the next ``advance``; any other reason counts as a refused start
    (``scheduler.count_refusal``: a bounded retry, then ``failed``)."""
    from ..runtime_target.device_wait import WAITABLE_REASONS

    kept = {"session_id": session_id} if session_id else {}
    if started.reason in WAITABLE_REASONS:
        return {"status": "pending", "reason": started.reason, **kept}
    return {"status": "pending", "refused": f"device_turn_refused: {started.reason}", **kept}


async def _start_item_thread(db: AsyncSession, run: WorkflowRun, item: dict[str, Any],
                             branched: dict[str, Any]) -> dict[str, Any]:
    from app.services.devices.job_state import ACTIVE_STATUSES

    from ...devices.chat_turn import DeviceTurnStarted, start_device_turn
    from ...devices.jobs import thread_job
    from ..octryx.phase_sessions import _job_session
    from ..octryx.run_turn import start_run_turn

    main, main_target = await _main_thread(db, run)
    node = await _parallel_node(db, run)
    if main is None or main_target is None or node is None:
        return {"status": "failed", "reason": "the run's main thread no longer runs on a device"}
    folder = branched.get("folder") or item_folder(str(main_target.get("folder") or ""), item["id"])
    target = {key: main_target.get(key) or "" for key in ("device_id", "profile", "model")} | {"folder": folder}
    thread = await _item_thread(db, run, item, main, target)
    last = await thread_job(db, thread.id)
    if last is not None and last.status in ACTIVE_STATUSES:
        # Its thread already runs a turn (a start whose ``running`` was not seen): that turn is the item's.
        return _running(run, item, branched, folder, thread.id, last.id)
    resume = _job_session(last) if last is not None and last.folder == folder else ""

    async def start(turn_target: dict[str, Any], suffix: str) -> Any:
        turn_target = {**turn_target, "folder": folder}  # a seat fallback never moves the item to the main folder
        return await start_device_turn(
            db, user_id=thread.user_id, target=turn_target,
            prompt=await _bound_prompt(db, run, item, resumed=bool(resume),
                                       conflicts=list(branched.get("conflicts") or [])),
            session_id=thread.id, fresh_session=not resume, resume_session_id=resume,
            idempotency_key=f"{PROVENANCE}:{run.id}:{item['id']}:{item.get('iteration') or 1}:"
                            f"{item.get('attempts') or 0}{_retry_suffix(item)}{suffix}"[:100])

    started, _target = await start_run_turn(db, run, _role_node(node, item), thread,
                                            {**target, "kind": "device"}, start,
                                            model=str(item.get("model") or ""))
    if not isinstance(started, DeviceTurnStarted):
        return _refusal(started, thread.id)
    return _running(run, item, branched, folder, thread.id, started.job_id)


def _retry_suffix(item: dict[str, Any]) -> str:
    """A start after a refused one is a new turn (the refused job's idempotency key would return that job)."""
    refusals = int(item.get("start_refusals") or 0)
    return f":r{refusals}" if refusals else ""


def _running(run: WorkflowRun, item: dict[str, Any], branched: dict[str, Any], folder: str, session_id: str,
             job_id: str) -> dict[str, Any]:
    return {"status": RUNNING, "session_id": session_id,
            "branch": branched.get("branch") or item_branch(run, item["id"]), "path": folder,
            "base": branched.get("head") or None, "job_id": job_id, "started_at": utc_now().isoformat()}


def sessions_key(node_id: str, key: str) -> str:
    return f"{node_id}/{key}"


async def _start_sequential(db: AsyncSession, run: WorkflowRun, item: dict[str, Any]) -> dict[str, Any]:
    """The item in the main folder on the main thread: its own fresh session (resumed when reopened)."""
    from app.services.devices.job_state import ACTIVE_STATUSES

    from ...devices.chat_turn import DeviceTurnStarted, start_device_turn
    from ...devices.jobs import thread_job
    from ..octryx.phase_sessions import SESSIONS_KEY, _session_here
    from ..octryx.run_turn import start_run_turn

    main, target = await _main_thread(db, run)
    node = await _parallel_node(db, run)
    if main is None or target is None or node is None:
        return {"status": "failed", "reason": "the run's main thread no longer runs on a device"}
    busy = await thread_job(db, main.id)
    if busy is not None and busy.status in ACTIVE_STATUSES:
        return {"status": "pending", "reason": "device_busy"}  # one at a time on the main thread
    entry = dict(dict(dict(run.context or {}).get(SESSIONS_KEY) or {}).get(sessions_key(node.id, item["id"])) or {})
    resume = await _session_here(db, entry, target)

    async def start(turn_target: dict[str, Any], suffix: str) -> Any:
        return await start_device_turn(
            db, user_id=main.user_id, prompt=await _bound_prompt(db, run, item, resumed=bool(resume)),
            target=turn_target,
            session_id=main.id, fresh_session=not resume, resume_session_id=resume,
            idempotency_key=f"{PROVENANCE}:seq:{run.id}:{item['id']}:{item.get('iteration') or 1}:"
                            f"{item.get('attempts') or 0}{_retry_suffix(item)}{suffix}"[:100])

    started, _target = await start_run_turn(db, run, _role_node(node, item), main, target, start,
                                            model=str(item.get("model") or ""))
    if not isinstance(started, DeviceTurnStarted):
        return _refusal(started)
    _set_state(run, {**_state(run), "sequential_job": {"job_id": started.job_id, "key": item["id"],
                                                        "turn_id": await _turn_of(db, started.job_id)}})
    return {"status": RUNNING, "session_id": main.id, "branch": run.branch, "path": target.get("folder"),
            "base": dict(run.context or {}).get("base_sha"), "job_id": started.job_id,
            "started_at": utc_now().isoformat()}
