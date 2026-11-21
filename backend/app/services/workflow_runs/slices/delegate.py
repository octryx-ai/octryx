"""Delegate a phase's slices to sub-agents: one named agent, one worktree branch, one child per slice.

The main agent of a phase that declares ``sub_agents`` calls ``delegate_slices`` with its slices
(``key``, ``title``, ``task``, optional ``tests`` and, for a re-delegation, ``findings``). The server, under the
run claim:

1. commits the run's working copy (the confirmed tests and anything written so far are the slices' common base);
2. per slice: a worktree on the branch ``<run branch>--<key>`` (reused on re-delegation; reset to the merged state
   after a conflict), a fresh child session whose workspace **is** that worktree, bound to the run as a ``child`` —
   so the child's turn gets the phase's own contract (class, tools, path rules, protected confirmed tests) through
   the ordinary run binding;
3. bounds the work: at most ``max_parallel`` (≤ 5) slices running at once, at most ``iterations`` per slice
   (beyond it the slice is ``limit`` and the phase's gate fails into its own bounded loop), and the time a child
   may take comes from the run's remaining time budget (no 300 s cap);
4. launches the children (the sub-agent group runner); the parent turn resumes when they are done.

A child's turn reports a structured slice result (``results.record_child_turn``), never the phase's.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun, WorkflowRunSession
from ....time_utils import utc_now
from ..records import RUN_METADATA_KEY, WorkflowRunError, lock_run, record_event
from ..states import STATUS_RUNNING
from . import worktrees
from .rules import sub_agent_config

ROLE_CHILD = "child"
SLICE_METADATA_KEY = "workflow_run_slice"
DEFAULT_SLICE_SECONDS = 3600
MAX_SLICE_SECONDS = 10_800
_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
Launcher = Callable[..., Awaitable[None]]


def slices_of(run: WorkflowRun) -> dict[str, dict[str, Any]]:
    return {key: dict(value) for key, value in dict(dict(run.context or {}).get("slices") or {}).items()
            if isinstance(value, dict)}


def remaining_seconds(run: WorkflowRun) -> int:
    """The time a child may take: what is left of the run's time budget, else the default; never the 300 s cap."""
    budget = dict(dict(run.limits or {}).get("budget") or {}).get("active_seconds")
    used = float(dict(run.budget_usage or {}).get("active_seconds") or 0)
    left = int(float(budget) - used) if budget else DEFAULT_SLICE_SECONDS
    return max(60, min(left, MAX_SLICE_SECONDS))


async def _named_agent(db: AsyncSession, name: str, user_id: str) -> dict[str, Any]:
    from ...agent_builtins import builtin_agent
    from ...agent_definition_execution import resolve_agent_definition_for_execution

    agent = await builtin_agent(db, name)
    definition_id = agent.id if agent is not None else name
    resolution = await resolve_agent_definition_for_execution(db, definition_id=definition_id,
                                                              visible_to_user_id=user_id)
    if not resolution.resolved:
        raise WorkflowRunError("sub_agent_unavailable", f"The phase's sub-agent '{name}' cannot run.", 409)
    return dict(resolution.payload or {})


def _plan(existing: dict[str, dict[str, Any]], requested: list[Any], *, iterations: int
          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(slices to start, refused slices)`` — nothing is started twice, nothing beyond its iterations."""
    start, refused = [], []
    for raw in requested:
        item = raw if isinstance(raw, dict) else {}
        key = str(item.get("key") or "").strip().lower()
        if not _KEY.match(key):
            refused.append({"key": key, "reason": "slice_key_invalid"})
            continue
        current = existing.get(key)
        if current is not None and current.get("status") == "running":
            refused.append({"key": key, "reason": "slice_running"})
            continue
        iteration = int((current or {}).get("iteration") or 0) + 1
        if iteration > iterations:
            refused.append({"key": key, "reason": "slice_iteration_limit"})
            continue
        findings = [str(text)[:500] for text in item.get("findings") or [] if str(text).strip()][:20]
        start.append({"key": key, "title": str(item.get("title") or (current or {}).get("title") or key)[:120],
                      "task": str(item.get("task") or (current or {}).get("task") or "")[:4000],
                      "tests": [str(test)[:300]
                                for test in item.get("tests") or (current or {}).get("tests") or []][:50],
                      "findings": findings, "iteration": iteration, "previous": current})
    return start, refused


def _child_task(run: WorkflowRun, slice_: dict[str, Any]) -> str:
    lines = [f"Slice '{slice_['key']}' of workflow run {run.workflow_key} ({run.ticket_key or run.title}): "
             f"{slice_['title']}", "", slice_["task"]]
    if slice_["tests"]:
        lines += ["", "Make these tests pass (never change a confirmed test):",
                  *[f"- {test}" for test in slice_["tests"]]]
    if slice_["findings"]:
        lines += ["", f"Iteration {slice_['iteration']}: fix these findings first:",
                  *[f"- {text}" for text in slice_["findings"]]]
    lines += ["", "Run the tests before you finish. Your workspace is this slice's own branch; "
                  "the main agent merges it."]
    return "\n".join(lines)


async def delegate_slices(
    db: AsyncSession, *, parent_session: Session, slices: list[Any], launcher: Launcher | None = None,
) -> dict[str, Any]:
    from ..graph import graph_for_run
    from ..records import active_run_for_session

    run = await active_run_for_session(db, parent_session.id)
    if run is None or SLICE_METADATA_KEY in dict(parent_session.metadata_ or {}):
        raise WorkflowRunError("not_a_run_phase", "Only the main agent of a workflow run phase delegates slices.", 409)
    run = await lock_run(db, run)
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    config = sub_agent_config(node.config) if node is not None else None
    if run.status != STATUS_RUNNING or config is None:
        raise WorkflowRunError("phase_without_sub_agents", "The current phase does not delegate to sub-agents.", 409)
    main = Path(str(dict(run.context or {}).get("local_path") or ""))
    if not str(main) or not (main / ".git").exists():
        raise WorkflowRunError("no_working_copy", "Slices need the run's repository working copy (create the branch "
                                                  "first).", 409)
    existing = slices_of(run)
    start, refused = _plan(existing, slices, iterations=config["iterations"])
    running = sum(1 for item in existing.values() if item.get("status") == "running")
    if running + len(start) > config["max_parallel"]:
        raise WorkflowRunError("parallel_limit", f"At most {config['max_parallel']} slices run at once "
                                                 f"({running} running).", 409)
    if not start:
        return {"status": "nothing_delegated", "refused": refused, "slices": list(existing.values())}
    await worktrees.commit_all(main, f"{run.ticket_key or 'workflow run'}: base for slices")
    base = await worktrees.head(main)
    payload = await _named_agent(db, config["agent"], run.requested_by)
    seconds = remaining_seconds(run)
    children = []
    for slice_ in start:
        previous = slice_.pop("previous") or {}
        path = Path(previous.get("path") or main.parent / f".slices-{run.id[:8]}" / slice_["key"])
        branch = previous.get("branch") or f"{run.branch or 'run-' + run.id[:8]}--{slice_['key']}"
        error = await worktrees.ensure_worktree(main, path, branch)
        if error:
            refused.append({"key": slice_["key"], "reason": "worktree_failed", "detail": error})
            continue
        if previous.get("status") in ("conflict", "failed", "limit"):
            await worktrees.reset_to(path, base)  # the slice builds on the merged state, its findings in the task
        child = Session(
            id=str(uuid.uuid4()), user_id=run.requested_by, project_id=run.project_id,
            agent_type=str(payload.get("agentType") or "coding"), status="active", origin="sub_agent",
            parent_session_id=parent_session.id, sub_agent_depth=1,
            metadata_={"title": f"Slice {slice_['key']}: {slice_['title']}"[:200], "trigger": "sub_agent",
                       "workspace_root": str(path), "runtime_request_timeout_seconds": seconds,
                       SLICE_METADATA_KEY: {"run_id": run.id, "key": slice_["key"]}, RUN_METADATA_KEY: run.id})
        db.add(child)
        await db.flush()
        if previous.get("child_session_id"):
            old = await db.get(Session, previous["child_session_id"])
            await _end_binding(db, run, old)
        db.add(WorkflowRunSession(run_id=run.id, session_id=child.id, role=ROLE_CHILD, runtime="chat", active=True))
        existing[slice_["key"]] = {
            **{key: slice_[key] for key in ("key", "title", "task", "tests", "findings", "iteration")},
            "status": "running", "branch": branch, "path": str(path), "base": base, "child_session_id": child.id,
            "agent": config["agent"], "seconds": seconds, "started_at": utc_now().isoformat(), "result": None}
        children.append({"session_id": child.id, "task": _child_task(run, slice_)})
    run.context = {**dict(run.context or {}), "slices": existing}
    record_event(db, run, "slices_delegated", node_id=run.current_node_id,
                 detail={"slices": [item["session_id"] for item in children], "refused": refused})
    if children:
        await (launcher or launch_children)(db, parent_session=parent_session, run=run, payload=payload,
                                            children=children, max_parallel=config["max_parallel"], seconds=seconds)
    return {"status": "delegated", "refused": refused,
            "slices": [slice_view(item) for item in existing.values()]}


async def _end_binding(db: AsyncSession, run: WorkflowRun, session: Session | None) -> None:
    from sqlalchemy import update

    if session is None:
        return
    await db.execute(update(WorkflowRunSession).where(
        WorkflowRunSession.run_id == run.id, WorkflowRunSession.session_id == session.id,
    ).values(active=False).execution_options(synchronize_session=False))


def slice_view(item: dict[str, Any]) -> dict[str, Any]:
    """What the run shows of a slice (the board): no paths, no task text."""
    return {key: item.get(key) for key in ("key", "title", "status", "iteration", "branch", "agent", "child_session_id",
                                           "result", "conflicts", "reason", "merged_sha")}


async def launch_children(db: AsyncSession, *, parent_session: Session, run: WorkflowRun, payload: dict[str, Any],
                          children: list[dict[str, str]], max_parallel: int, seconds: int) -> None:
    """The sub-agent group runner (the same one ``spawn_sub_agent`` uses); the parent resumes when all are done."""
    from sqlalchemy.ext.asyncio import AsyncSession as Async
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from ...session.run_state import RUN_STATUS_AWAITING_SUBAGENTS, set_session_run_state
    from ...sub_agent_group import create_sub_agent_group, launch_sub_agent_group

    group = await create_sub_agent_group(db, parent_session_id=parent_session.id,
                                         child_session_ids=[item["session_id"] for item in children],
                                         timeout_seconds=seconds, resume_prompt=None)
    metadata = dict(parent_session.metadata_ or {})
    metadata.update(current_sub_agent_group_id=group.id,
                    sub_agent_group_child_session_ids=[item["session_id"] for item in children])
    parent_session.metadata_, parent_session.status = metadata, "awaiting_subagents"
    set_session_run_state(parent_session, RUN_STATUS_AWAITING_SUBAGENTS, "waiting_for_sub_agents")
    await db.commit()
    await launch_sub_agent_group(
        session_factory=async_sessionmaker(bind=db.bind, class_=Async, expire_on_commit=False), group_id=group.id,
        parent_session_id=parent_session.id, user_id=run.requested_by, project_id=run.project_id,
        agent_type=str(payload.get("agentType") or "coding"), runtime_target_id=None, thinking_level=None,
        agent_definition=payload, sub_agent_depth=1, child_runs=children, max_concurrent_children=max_parallel)


__all__ = ["ROLE_CHILD", "SLICE_METADATA_KEY", "delegate_slices", "launch_children", "remaining_seconds",
           "slice_view", "slices_of"]
