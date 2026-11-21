"""Teamwork: the coordinator splits a story's work at run time; ``parallel_work`` runs the split.

The coordinator is an ordinary phase with ``output: "work_plan"``
(``submit_work_plan``): a set of items with dependencies, the paths each one owns and its proof tests. A
``parallel_work`` node then runs that plan: every item whose dependencies are merged starts as its own agent session
(its role's rules, its own model) in its own working copy; each finished item is merged into the story at once; when
every item is merged the node routes ``done``; a failed, blocked or conflicting item that leaves nothing to run routes
``replan``, a loop back to the coordinator. The fixed backend → frontend → tests chain disappears.

FROZEN INTERFACE (the device executor and the board build against it; change it only together with
them). Everything below is importable from this package.

1. ``context.work`` (``WORK_KEY``) — the run's current split, written only by ``teamwork.scheduler``::

    {
      "node_id": "<parallel_work node id>",          # the node that runs the plan
      "plan_node": "<plan phase id>",                # the phase that submits it (config.plan)
      "plan_version": 3,                             # context.outputs.work_plan.version this split comes from
      "plan_hash": "sha256:...",
      "contract": "<the shared interface text>",
      "coordinator_session_id": "<session that submitted the plan>" | None,
      "coordinator_hash": "<board agent hash of that session>" | None,   # filled for device sessions
      "executor": "server" | "device" | "sequential",                    # who runs the items (chosen on entry)
      "route": None | "done" | "replan",                                 # set when the node resolved
      "updated_at": "<iso>",
      "items": {
        "<id>": {
          # from the plan (teamwork.plan.ITEM_FIELDS)
          "id", "title", "role", "model" (str | None), "depends_on": [ids], "paths": [globs],
          "appends_to": [shared files of items it depends on, where it only adds entries],   # optional
          "instructions", "proofs": [canonical test ids, each under its own paths],
          # run state
          "status": "pending" | "running" | "done" | "merged" | "failed" | "blocked" | "conflict",
          "iteration": 1,             # +1 when a revision reopens it (its own session resumes)
          "attempts": 0,              # starts in this iteration (a transient failure retries once)
          "session_id": str | None,   # the item's chat Session (origin sub_agent, parent = the main thread)
          "branch": str | None,       # "<run branch>--<id>"
          "path": str | None,         # the item's working copy (server worktree / device <main>/.octryx-items/<id>)
          "base": str | None,         # the commit the item started from
          "runtime_target_id": str | None,   # server: the runtime target serving ``model``
          "agent_hash": str | None,   # device: the board agent hash of its gateway session
          "job_id": str | None,       # device: the octryx job running it
          "result": {"value": "done" | "blocked", "summary": str} | None,   # submit_phase_result of the item
          "reason": str | None,       # why failed / blocked / conflict / pending again
          "start_refusals": int,      # starts refused in a row before the agent ran (scheduler.count_refusal)
          "retry_at": iso | None,     # a refused start waits until then (backoff); the same session starts again
          "start_detail": str | None, # why the device could not prepare the item's folder (its last report)
          "conflicts": [files] | None,
          "merged_sha": str | None,
          "started_at", "finished_at", "merged_at": iso | None,
        }
      }
    }

   Status flow: ``pending`` → ``running`` (once every ``depends_on`` item is ``merged``) → ``done`` → ``merged``;
   from ``running`` also ``failed`` or ``blocked``; from ``done`` also ``conflict`` (its merge conflicted).

2. Scheduler API (``teamwork.scheduler``; every call holds the run claim, ``records.lock_run``):

   - ``await enter(db, run, node, *, graph) -> str | None`` — the engine entered the ``parallel_work`` node: the
     split is (re)built from the recorded plan (revision rules of ``teamwork.plan``), then ``advance``. Returns the
     route when the node is decided at once, else ``None``: the engine waits (``_WAIT``) and the scheduler resolves
     the node later with ``engine.resolve_current_node(run, "done" | "replan")``.
   - ``await advance(db, run) -> str | None`` — start what can start, resolve the node when nothing more can
     happen. Call it on: node entry, an item's end, a merge report, a device job freeing a slot, a plan revision.
     Returns the route it resolved with, else ``None``.
   - ``await item_finished(db, run, *, key, session_id, state, transient=False, reason=None)`` — an item's turn
     ended. ``state`` is the turn's check state (``"passed"`` | ``"failed"``); its recorded result
     (``submit_phase_result``: done / blocked) is already on the item. ``transient=True``: the turn failed for a
     model/transport reason, not on its checks — retried once by resuming its session. A ``done`` item is handed to
     the executor's ``merge``. A report from an older session of the item changes nothing.
   - ``await merge_reported(db, run, *, key, merged, conflicts=None, merged_sha=None)`` — the item's merge into
     the story's working copy happened (server: at once in ``item_finished``; device: the launcher's work-git
     report): ``merged`` or ``conflict`` with the files; then ``advance``.

3. Executor protocol (``Executor``): who runs the items. ``teamwork.scheduler`` picks one on entry
   (``scheduler.choose_executor``, stored as ``context.work.executor``; later calls get it back with
   ``scheduler.executor_of``); ``server`` is built in (``teamwork.server_items``); the device side adds
   ``device`` (and the sequential fallback) with ``register_executor(name, async factory(db, run), first=True)``.
   All methods run under the run claim.

   - ``capacity(run) -> int | None`` — how many items may run at once (``None``: no bound of its own).
   - ``await start(db, run, item) -> dict`` — start (or resume, when ``item["session_id"]`` is set) the item's
     agent session. Returns the item fields to store: ``{"status": "running", "session_id", "branch", "path",
     "base", "runtime_target_id", ...}``, or ``{"status": "pending", "reason": "device_busy"}`` to try again on the
     next ``advance``, or ``{"status": "failed", "reason": "..."}``.
   - ``await merge(db, run, item) -> None`` — the item is ``done``: merge it into the story's working copy. Calls
     ``scheduler.merge_reported`` itself when it merges synchronously (server); the device queues a work-git step.
   - ``await finish(db, run) -> None`` — every item is merged (route ``done``): tidy up (server: soft-reset the
     working copy to ``context.base_sha`` so the story pushes as one change; remove worktrees).

4. Item marker. An item's Session carries ``metadata_[ITEM_METADATA_KEY] = {"run_id", "node_id", "key",
   "iteration"}`` (and ``workflow_run_id``), bound to the run as ``WorkflowRunSession`` role ``ROLE_ITEM``. Its
   turn's routing resolution marker gets ``"item": <key>`` (as a slice's gets ``"slice"``); ``record_phase_turn``
   routes it to ``scheduler.item_finished`` and never advances the node itself. Use ``item_key_of(session)``.
   A device item's gateway session (bound as ``octryx:<key>``) carries a copy of the marker and reports with its own
   session id: every check accepts the item's thread *or* a session whose marker names this run and item
   (``session_works_on``), so the item's Stop and its submissions are never dropped as an older session's.

5. Item contract: ``teamwork.item_definition.item_definition(run, node, item)`` (the definition) and
   ``item_node(run, node, item)`` (the synthetic phase node itself) — a synthetic phase (id = the
   ``parallel_work`` node id) from the role template plus the item's instructions, ``path_rules.write = paths``,
   its proofs as its task list, the shared contract and the team, ``result_values: ["done", "blocked"]``, through
   the unchanged ``phase_definition``.
"""

from __future__ import annotations

from typing import Any, Protocol

WORK_KEY = "work"
ITEM_METADATA_KEY = "workflow_run_item"
ROLE_ITEM = "item"
OUTPUT_KIND = "work_plan"
OUTPUT_TOOL = "submit_work_plan"

ROUTE_DONE, ROUTE_REPLAN = "done", "replan"
ROUTES = frozenset({ROUTE_DONE, ROUTE_REPLAN})

PENDING, RUNNING, DONE, MERGED = "pending", "running", "done", "merged"
FAILED, BLOCKED, CONFLICT = "failed", "blocked", "conflict"
STATUSES = frozenset({PENDING, RUNNING, DONE, MERGED, FAILED, BLOCKED, CONFLICT})
STUCK = frozenset({FAILED, BLOCKED, CONFLICT})  # nothing more happens to them until the coordinator replans

RESULT_DONE, RESULT_BLOCKED = "done", "blocked"
ITEM_RESULT_VALUES = (RESULT_DONE, RESULT_BLOCKED)

EXECUTOR_SERVER, EXECUTOR_DEVICE, EXECUTOR_SEQUENTIAL = "server", "device", "sequential"


class Executor(Protocol):
    """Runs a plan's items (see the module docstring, point 3)."""

    name: str

    def capacity(self, run: Any) -> int | None: ...

    async def start(self, db: Any, run: Any, item: dict[str, Any]) -> dict[str, Any]: ...

    async def merge(self, db: Any, run: Any, item: dict[str, Any]) -> None: ...

    async def finish(self, db: Any, run: Any) -> None: ...


# name -> ``async factory(db, run)`` returning an Executor, or None when it does not run this run (the next
# registered one is tried; ``server`` takes every run it is asked for).
_EXECUTORS: dict[str, Any] = {}


def register_executor(name: str, factory: Any, *, first: bool = False) -> None:
    """Make an executor available to ``choose_executor``; ``first`` tries it before those already registered (the
    device side registers ``device`` first, so a device run never falls through to the server)."""
    global _EXECUTORS
    _EXECUTORS.pop(name, None)
    _EXECUTORS = {name: factory, **_EXECUTORS} if first else {**_EXECUTORS, name: factory}


def executors() -> dict[str, Any]:
    return dict(_EXECUTORS)


def work_of(run: Any) -> dict[str, Any]:
    """The run's ``context.work`` (a copy; ``{}`` before a plan ran)."""
    value = dict(getattr(run, "context", None) or {}).get(WORK_KEY)
    return dict(value) if isinstance(value, dict) else {}


def item_marker(session: Any) -> dict[str, Any] | None:
    marker = dict(getattr(session, "metadata_", None) or {}).get(ITEM_METADATA_KEY)
    return dict(marker) if isinstance(marker, dict) and marker.get("key") else None


def session_works_on(run: Any, item: dict[str, Any], session: Any) -> bool:
    """Whether ``session`` is ``item``'s session in ``run``: its thread, or a gateway session carrying its marker
    (a device item's Claude Code session). A session of an earlier iteration does not count."""
    if session is None or not item:
        return False
    if str(getattr(session, "id", "") or "") == str(item.get("session_id") or "~"):
        return True
    marker = item_marker(session) or {}
    iteration = marker.get("iteration")
    return (marker.get("run_id") == getattr(run, "id", None) and str(marker.get("key")) == str(item.get("id"))
            and (iteration is None or int(iteration) == int(item.get("iteration") or 1)))


def item_key_of(session: Any) -> str | None:
    marker = item_marker(session)
    return str(marker["key"]) if marker else None


__all__ = [
    "BLOCKED", "CONFLICT", "DONE", "EXECUTOR_DEVICE", "EXECUTOR_SEQUENTIAL", "EXECUTOR_SERVER", "Executor", "FAILED",
    "ITEM_METADATA_KEY", "ITEM_RESULT_VALUES", "MERGED", "OUTPUT_KIND", "OUTPUT_TOOL", "PENDING", "RESULT_BLOCKED",
    "RESULT_DONE", "ROLE_ITEM", "ROUTES", "ROUTE_DONE", "ROUTE_REPLAN", "RUNNING", "STATUSES", "STUCK", "WORK_KEY",
    "executors", "item_key_of", "item_marker", "register_executor", "session_works_on", "work_of",
]
