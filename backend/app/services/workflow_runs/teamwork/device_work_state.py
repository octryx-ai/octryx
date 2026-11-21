"""The run's teamwork git state on the device (``context.work_git``): its keys, fallbacks, folders and turns."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ..graph import PhasedNode
from ..records import main_session_id
from . import work_of

GIT_KEY = "work_git"
RELEASED_KEPT = 20  # bookkeeping of released main-thread turns (each ends once); never a limit on work


# A gateway session of the coordinator's board wake (``teamwork.coordinator``) on the main thread: its contract shows
# the plan phase (answer, revise the plan); its Stop is never a phase pass of the ``parallel_work`` node.
COORDINATOR_METADATA_KEY = "workflow_run_coordinator_wake"
ITEMS_DIR = ".octryx-items"  # octryx-claude work_git.ITEMS_DIR
PROVENANCE = "teamwork"
EVENT_SEQUENTIAL = "teamwork_sequential_fallback"
EVENT_COMMIT_GUARDED = "teamwork_plan_commit_kept_merged_files"
FALLBACK_ONE_SLOT = "device_runs_one_job"
FALLBACK_NOT_PARALLEL = "node_not_parallel"
FALLBACK_BRANCH_FAILED = "branch_failed"


def _state(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(GIT_KEY) or {})


def _set_state(run: WorkflowRun, state: dict[str, Any]) -> None:
    """Stored as its own copy: a later in-place change is never mistaken for the stored value (``scheduler._store``)."""
    run.context = {**dict(run.context or {}), GIT_KEY: copy.deepcopy(state)}


def item_branch(run: WorkflowRun, key: str) -> str:
    return f"{run.branch or 'run-' + run.id[:8]}--{key}"


def item_folder(main_folder: str, key: str) -> str:
    return f"{str(main_folder).rstrip('/')}/{ITEMS_DIR}/{key}"


async def _main_thread(db: AsyncSession, run: WorkflowRun) -> tuple[Session | None, dict[str, Any] | None]:
    from ..octryx.continuation_marker import _device_target

    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    return thread, _device_target(thread)


async def _parallel_node(db: AsyncSession, run: WorkflowRun) -> PhasedNode | None:
    from ..graph import graph_for_run

    node_id = str(work_of(run).get("node_id") or run.current_node_id or "")
    return (await graph_for_run(db, run)).nodes.get(node_id)


async def _turn_of(db: AsyncSession, job_id: str) -> str | None:
    from ....models import DeviceJob

    job = await db.get(DeviceJob, job_id)
    return job.turn_id if job is not None else None


def _is_turn(entry: Any, job: Any) -> bool:
    """Whether ``job``'s current turn is the one ``entry`` (``sent``, ``sequential_job``) started. The turn, not the
    job: the git work and a sequential item run on the main thread's own job, reused for the coordinator's next turn
    (one main job, turns phase, git, plan). A job id alone would claim that next turn
    as teamwork's and swallow the coordinator's turn end. An entry without a turn id matches by
    job."""
    entry = dict(entry or {})
    if job is None or not entry.get("job_id") or entry.get("job_id") != getattr(job, "id", None):
        return False
    return not entry.get("turn_id") or entry["turn_id"] == getattr(job, "turn_id", None)
