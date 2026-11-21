"""The server executor: each item works in its own git worktree beside the run's working copy (design section 4).

Reuses the slices' shape (``slices/delegate``, ``slices/worktrees``):

- **start**: the run's working copy (``context.local_path``) is committed (the coordinator's ``docs/stories`` are the
  items' common base); the item gets a worktree on ``<run branch>--<id>`` from the current HEAD — so an item that
  depends on others starts from their merged state — and a chat ``Session`` whose ``workspace_root`` is that worktree,
  bound to the run as role ``item`` with the item marker. Its turn starts after the commit, on the runtime target
  that serves the item's model (``phase_runtime_target_id``); a model the Workspace refuses falls back to the thread's
  runtime with ``run_turn_model_refused``, as for a phase. A reopened item, or one retried after a conflict, starts
  over from the merged HEAD in its own session; a transient retry resumes as it was.
- **merge**: the item's worktree is committed and merged into the working copy at once, under the run claim; a
  conflict is aborted (the copy stays as it was) and reported with its files.
- **finish**: every item merged: the working copy is soft-reset to ``context.base_sha`` (the story pushes as one
  change, as merged slices do) and the worktrees are removed. Item branches stay local; nothing is pushed.

The sub-agent group runner is not used: it has one runtime target for the whole group and resumes the parent with a
prompt, while each item has its own model and the scheduler, not the parent, decides what comes next.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import event

from ....models import Session, WorkflowRun, WorkflowRunSession
from ..records import RUN_METADATA_KEY, record_event
from ..slices import worktrees
from . import EXECUTOR_SERVER, ITEM_METADATA_KEY, ROLE_ITEM, register_executor, work_of

logger = logging.getLogger(__name__)

_AFTER_COMMIT_KEY = "workflow_teamwork_item_turns"


def _main(run: WorkflowRun) -> Path:
    return Path(str(dict(run.context or {}).get("local_path") or ""))


def item_path(run: WorkflowRun, key: str) -> Path:
    return _main(run).parent / f".items-{run.id[:8]}" / key


def item_branch(run: WorkflowRun, key: str) -> str:
    return f"{run.branch or 'run-' + run.id[:8]}--{key}"


class ServerExecutor:
    name = EXECUTOR_SERVER

    def capacity(self, run: WorkflowRun) -> int | None:
        return None  # model turns on the server have no slot bound of their own

    async def start(self, db: Any, run: WorkflowRun, item: dict[str, Any]) -> dict[str, Any]:
        return await start_server_item(db, run, item)

    async def merge(self, db: Any, run: WorkflowRun, item: dict[str, Any]) -> None:
        await merge_server_item(db, run, item)

    async def finish(self, db: Any, run: WorkflowRun) -> None:
        await finish_server_items(db, run)


async def _factory(db: Any, run: WorkflowRun) -> ServerExecutor:
    return ServerExecutor()


register_executor(EXECUTOR_SERVER, _factory)


async def _role_template(db: Any, run: WorkflowRun, item: dict[str, Any]) -> dict[str, Any]:
    from ..graph import graph_for_run
    from .node import roles_of

    node = (await graph_for_run(db, run)).nodes.get(str(work_of(run).get("node_id") or ""))
    return dict(roles_of(node).get(str(item.get("role") or "")) or {}) if node is not None else {}


async def start_server_item(db: Any, run: WorkflowRun, item: dict[str, Any]) -> dict[str, Any]:
    """Start (or resume) the item's session in its own worktree; the item fields to store."""
    from ..records import main_session_id
    from ..server_continuation import phase_runtime_target_id

    main = _main(run)
    if not str(main) or not (main / ".git").exists():
        return {"status": "failed", "reason": "no working copy on the server (create the branch first)"}
    key = str(item["id"])
    await worktrees.commit_all(main, f"{run.ticket_key or run.workflow_key}: base for item {key}")
    base = await worktrees.head(main)
    path = Path(str(item.get("path") or item_path(run, key)))
    branch = str(item.get("branch") or item_branch(run, key))
    error = await worktrees.ensure_worktree(main, path, branch)
    if error:
        return {"status": "failed", "reason": f"worktree failed: {error}"}
    transient = item.get("reason") == "transient_retry" and item.get("session_id")
    if not transient:
        await worktrees.reset_to(path, base)  # a reopened or retried item builds on the merged state
    template = await _role_template(db, run, item)
    model = str(item.get("model") or template.get("model") or "")
    runtime_target_id = await phase_runtime_target_id(db, model) if model else None
    session = await db.get(Session, str(item.get("session_id") or "")) if item.get("session_id") else None
    marker = {"run_id": run.id, "node_id": run.current_node_id, "key": key, "iteration": item.get("iteration") or 1}
    if session is None:
        parent_id = await main_session_id(db, run)
        session = Session(
            id=str(uuid.uuid4()), user_id=run.requested_by, project_id=run.project_id,
            agent_type=await _agent_type(db, run, template), status="active", origin="sub_agent",
            parent_session_id=parent_id, sub_agent_depth=1,
            metadata_={"title": f"Item {key}: {item.get('title') or key}"[:200], "trigger": "sub_agent",
                       "workspace_root": str(path), ITEM_METADATA_KEY: marker, RUN_METADATA_KEY: run.id})
        db.add(session)
        await db.flush()
        db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role=ROLE_ITEM, runtime="chat",
                                  active=True))
    else:
        session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(path), ITEM_METADATA_KEY: marker}
    await db.flush()
    _after_commit(db, (run.id, key, session.id, runtime_target_id))
    return {"status": "running", "session_id": session.id, "branch": branch, "path": str(path), "base": base,
            "runtime_target_id": runtime_target_id, "reason": None}


async def _agent_type(db: Any, run: WorkflowRun, template: dict[str, Any]) -> str:
    from ..records import WorkflowRunError
    from ..slices.delegate import _named_agent

    try:
        payload = await _named_agent(db, str(template.get("agent") or ""), run.requested_by)
    except WorkflowRunError:
        return "coding"  # the phase-agent binding at turn start holds the turn with the reason
    return str(payload.get("agentType") or "coding")


async def merge_server_item(db: Any, run: WorkflowRun, item: dict[str, Any]) -> None:
    """Commit the item's worktree and merge its branch into the run's working copy now."""
    from .item_results import merge_reported

    key, main = str(item["id"]), _main(run)
    await worktrees.commit_all(Path(str(item.get("path") or "")),
                               f"{run.ticket_key or run.workflow_key}: item {key} (iteration {item.get('iteration')})")
    await worktrees.commit_all(main, f"{run.ticket_key or run.workflow_key}: before merging item {key}")
    merged, conflicts = await worktrees.merge(main, str(item.get("branch") or item_branch(run, key)),
                                              f"{run.ticket_key or run.workflow_key}: merge item {key}")
    await merge_reported(db, run, key=key, merged=merged, conflicts=conflicts,
                         merged_sha=await worktrees.head(main) if merged else None)


async def finish_server_items(db: Any, run: WorkflowRun) -> None:
    """Every item is merged: the story lands uncommitted on its base, the worktrees go."""
    main = _main(run)
    base = str(dict(run.context or {}).get("base_sha") or "")
    if base and (main / ".git").exists():
        await worktrees.git(main, "reset", "--soft", base)
    for item in dict(work_of(run).get("items") or {}).values():
        if item.get("path") and Path(str(item["path"])).exists():
            await worktrees.git(main, "worktree", "remove", "--force", str(item["path"]))


# --- the item's turn ---------------------------------------------------------------------------------------------


def item_prompt(run: WorkflowRun, item: dict[str, Any]) -> str:
    from ..run_texts import run_text

    return run_text("server_item.build", item_id=item.get("id"), role=item.get("role"), workflow_key=run.workflow_key,
                    ticket=run.ticket_key or run.title, title=item.get("title"))


def _after_commit(db: Any, turn: tuple[str, str, str, str | None]) -> None:
    sync = db.sync_session
    sync.info.setdefault(_AFTER_COMMIT_KEY, set()).add(turn)
    if not event.contains(sync, "after_commit", _schedule_pending):
        event.listen(sync, "after_commit", _schedule_pending)
        event.listen(sync, "after_rollback", _drop_pending)


def _schedule_pending(sync_session: Any) -> None:
    for run_id, key, session_id, target in sync_session.info.pop(_AFTER_COMMIT_KEY, set()):
        schedule_item_turn(run_id, key, session_id, target)


def _drop_pending(sync_session: Any) -> None:
    sync_session.info.pop(_AFTER_COMMIT_KEY, None)


def schedule_item_turn(run_id: str, key: str, session_id: str, runtime_target_id: str | None, *,
                       session_factory=None) -> None:
    import asyncio

    from ...chat_turn_background import schedule_chat_turn_background_task

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    schedule_chat_turn_background_task(
        session_id=session_id, task_name="workflow_teamwork_item",
        coro_factory=lambda: run_item_turn(run_id, key, session_id, runtime_target_id,
                                           session_factory=session_factory))


_MODEL_REFUSALS = frozenset({"runtime_not_allowed", "runtime_requirement_unmet", "runtime_target_invalid"})


async def run_item_turn(run_id: str, key: str, session_id: str, runtime_target_id: str | None, *,
                        session_factory=None, send=None) -> None:
    """Send the item's turn on its own runtime target (``send``: ``send_session_message``, injectable for tests)."""
    from ....db import core as db_core
    from ...session.message_dispatch import send_session_message
    from ...session.turn_refusals import TurnRefusal
    from ..server_continuation import EVENT_MODEL_REFUSED

    factory = session_factory or db_core.async_session_factory
    send = send or send_session_message
    async with factory() as db:
        run = await db.get(WorkflowRun, run_id)
        item = dict(dict(work_of(run).get("items") or {}).get(key) or {}) if run is not None else {}
        session = await db.get(Session, session_id)
        if (run is None or session is None or item.get("session_id") != session_id
                or item.get("status") != "running"):
            return
        from ..run_texts import run_texts

        async with run_texts(db, run):
            prompt = item_prompt(run, item)
        user_id, project_id = session.user_id, session.project_id

        async def turn(target: str | None):
            return await send(db, session_id=session_id, content=prompt, user_id=user_id, project_id=project_id,
                              runtime_target_id=target, session_factory=factory)

        try:
            outcome = await turn(runtime_target_id)
            if runtime_target_id and isinstance(outcome, TurnRefusal) and str(outcome.state) in _MODEL_REFUSALS:
                run = await db.get(WorkflowRun, run_id)
                record_event(db, run, EVENT_MODEL_REFUSED, node_id=run.current_node_id,
                             detail={"runtime_target_id": runtime_target_id, "reason": str(outcome.state),
                                     "item": key})
                await db.commit()
                outcome = await turn(None)
        except Exception:  # noqa: BLE001 - the turn runner settled the turn; the item must not stay running
            logger.warning("workflow_run.teamwork_item_turn_failed run_id=%s item=%s", run_id, key, exc_info=True)
            await _turn_failed(factory, session_id, transient=True, reason="the item's turn could not run")
            return
        if isinstance(outcome, TurnRefusal):
            await _turn_failed(factory, session_id, transient=False,
                               reason=f"the platform could not start the item's turn ({outcome.state})")


async def _turn_failed(factory: Any, session_id: str, *, transient: bool, reason: str) -> None:
    async with factory() as db:
        await _ended(db, session_id, failed=True, transient=transient, reason=reason)
        await db.commit()


async def turn_ended(session_id: str, *, failed: bool, session_factory=None) -> bool:
    """The chat turn of ``session_id`` ended (``turn_settlement``). ``True`` when it is an item's session (then
    nothing else continues on it): a failed turn is transient (retried once), a turn that ended without its report
    (``record_phase_turn`` already moved a reported item on) is failed."""
    from ....db import core as db_core

    factory = session_factory or db_core.async_session_factory
    async with factory() as db:
        session = await db.get(Session, session_id)
        if session is None or not isinstance(dict(session.metadata_ or {}).get(ITEM_METADATA_KEY), dict):
            return False
        await _ended(db, session_id, failed=failed, transient=failed,
                     reason=None if failed else "its turn ended without a result")
        await db.commit()
    return True


async def _ended(db: Any, session_id: str, *, failed: bool, transient: bool, reason: str | None) -> None:
    from ..records import WorkflowRunError, lock_run_id
    from . import item_marker
    from .item_results import item_finished

    marker = item_marker(await db.get(Session, session_id)) or {}
    try:
        run = await lock_run_id(db, str(marker.get("run_id") or ""))
    except WorkflowRunError:
        return
    if run is None:
        return
    item = dict(dict(work_of(run).get("items") or {}).get(str(marker.get("key"))) or {})
    if item.get("status") != "running" or item.get("session_id") != session_id:
        return
    await item_finished(db, run, key=str(marker["key"]), session_id=session_id, state="failed",
                        transient=transient and failed, reason=reason)


__all__ = ["ServerExecutor", "finish_server_items", "item_branch", "item_path", "item_prompt", "merge_server_item",
           "run_item_turn", "schedule_item_turn", "start_server_item", "turn_ended"]
