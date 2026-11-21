"""The one folder a server phase turn works in: the run's prepared working copy.

``workspace.prepare`` checks the run's branch out in the run's working copy (``run.context.local_path``, on the run's
base); the run's tests, the reviewed tree and the push read that copy. A server phase turn's tools used the chat
session's own workspace instead — empty for a run: a read-only phase fell back to a stale Knowledge snapshot, and a
change phase would write (and run its tests) where nothing of the run is.

For a phase turn of the run's **main** session on the **server** runtime, this module decides one root:

- the tools' root (``run_context_config``): reads, writes and ``run_test_suite`` land in the working copy;
- the phase path rules and the confirmed-test protection (``path_rules``) resolve the tools' relative paths against
  the same copy;
- a **change** phase (``change`` / ``deliver``) without a prepared copy, and any phase whose run declares a copy
  that is not usable (``local_path`` set, folder gone), is held ``needs_configuration`` at turn resolution
  (:func:`phase_copy_refusal`): never a silent fallback to the session folder. A read-only phase of a run that
  declares no copy keeps the session workspace (phases of A/E without a repository).

A slice child and a ``parallel_work`` item keep their own worktree (their session's ``workspace_root``); device
and terminal runs work in their own folder (``octryx``) and are unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .states import RUN_RESOLUTION_KEY

READ_ONLY_CLASS = "read_only"
RUN_WORKING_COPY_KEY = "run_working_copy"
RUN_BASE_SHA_KEY = "run_base_sha"
# The one action that re-creates a server copy (``workspace/recovery``): it is offered on the run card, also while a
# phase is held.
RECREATE_ACTION = "On the run card choose 'Change where the run executes' → Server"
NO_WORKING_COPY_REASON = (
    "This phase changes the repository on the server, but the run has no server working copy of its branch (it was "
    "never prepared on the server). Run it where its copy is — 'Change where the run executes' → its device — or "
    "start a new run."
)
LOST_WORKING_COPY_REASON = (
    "The run's working copy is missing on the server (for example after the server was restarted). "
    f"{RECREATE_ACTION}: the platform re-creates it from the run's repository and branch, checks it against the "
    "run's base, and the phase continues."
)


def run_copy_trace_fields(project_config: dict[str, Any] | None) -> dict[str, Any]:
    """The run's working copy and base as the turn's trace records them (empty outside a run's copy)."""
    config = project_config if isinstance(project_config, dict) else {}
    if not config.get(RUN_WORKING_COPY_KEY):
        return {}
    return {RUN_WORKING_COPY_KEY: config[RUN_WORKING_COPY_KEY], RUN_BASE_SHA_KEY: config.get(RUN_BASE_SHA_KEY)}


def run_working_copy(run: Any) -> Path | None:
    """The run's prepared working copy when it exists on this server, else ``None``."""
    local_path = str(dict(getattr(run, "context", None) or {}).get("local_path") or "")
    if not local_path:
        return None
    root = Path(local_path).expanduser().resolve()
    # A folder that is not a git working copy is not the run's copy (never a foreign folder's content).
    return root if (root / ".git").exists() else None


async def _on_server(db: AsyncSession, run: Any) -> bool:
    from .workspace.preparation import RUNTIME_SERVER, runtime_of

    return await runtime_of(db, run) == RUNTIME_SERVER


async def phase_working_copy(db: AsyncSession, session_metadata: dict[str, Any]) -> tuple[Path, str] | None:
    """``(working copy, base sha)`` for a server turn of the run's main session whose run declares a copy.

    A declared copy whose folder is gone is still the root, with no base (``""``): the turn is held at resolution
    (:func:`phase_copy_refusal`), and nothing may meanwhile fall back to the session folder or read as verified.
    """
    from ..workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

    resolution = session_metadata.get(ROUTING_RESOLUTION_KEY)
    if not isinstance(resolution, dict):
        return None
    marker = resolution.get(RUN_RESOLUTION_KEY)
    if not isinstance(marker, dict) or not marker.get("run_id") or marker.get("slice") or marker.get("item"):
        return None  # a slice child and a parallel_work item work in their own worktree
    from ...models import WorkflowRun

    run = await db.get(WorkflowRun, str(marker["run_id"]))
    declared = str(dict(run.context or {}).get("local_path") or "") if run is not None else ""
    if not declared or not await _on_server(db, run):
        return None
    root = run_working_copy(run)
    if root is None:
        return Path(declared).expanduser().resolve(), ""
    return root, str(dict(run.context or {}).get("base_sha") or "")


def code_index_repository_id(params: dict[str, Any], project_config: dict[str, Any] | None) -> str | None:
    """The stored index a code-intelligence call may read: none inside a run's working copy.

    A registered repository's stored index is at whatever commit it was last built at, not the run's base; inside a
    phase turn the code tools read the working copy itself (the index is built from it on the fly)."""
    if (project_config or {}).get(RUN_WORKING_COPY_KEY):
        return None
    return str(params.get("repository_id") or "").strip() or None


async def phase_copy_refusal(db: AsyncSession, run: Any, phase_capability_class: str) -> str | None:
    """Why a phase cannot run on the server without its working copy, else ``None``.

    A run that declares a copy (``local_path``) whose folder is gone holds every phase; a change phase needs one.
    """
    if run_working_copy(run) is not None:
        return None
    declared = bool(str(dict(getattr(run, "context", None) or {}).get("local_path") or ""))
    if not declared and phase_capability_class == READ_ONLY_CLASS:
        return None  # a repository-independent phase
    if not await _on_server(db, run):
        return None
    return LOST_WORKING_COPY_REASON if declared else NO_WORKING_COPY_REASON


async def phase_rules_root(db: AsyncSession, session: Any, run: Any) -> Path | None:
    """The root the phase path rules resolve a server write against: the copy the turn's tools write in."""
    from .slices.delegate import SLICE_METADATA_KEY
    from .teamwork import ITEM_METADATA_KEY

    if session is None or {SLICE_METADATA_KEY, ITEM_METADATA_KEY} & set(dict(session.metadata_ or {})):
        return None
    root = run_working_copy(run)
    return root if root is not None and await _on_server(db, run) else None


__all__ = [
    "LOST_WORKING_COPY_REASON",
    "NO_WORKING_COPY_REASON",
    "RUN_BASE_SHA_KEY",
    "RUN_WORKING_COPY_KEY",
    "code_index_repository_id",
    "phase_copy_refusal",
    "phase_rules_root",
    "phase_working_copy",
    "run_copy_trace_fields",
    "run_working_copy",
]
