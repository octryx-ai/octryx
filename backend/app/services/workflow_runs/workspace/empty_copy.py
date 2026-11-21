"""Whether the platform knows a run's working copy holds no file at all (an empty repository).

A phase that asks "the code was read" (a blocking ``tool_called`` over the read tools only,
``workflow_checks.library.READ_TOOLS``) can never pass on a repository without files: there is nothing a read can
succeed on. Otherwise an agent that answered correctly on a repository with commits but no file ("the repository is
empty, the basis is the work item only", whose text the phase prompt carries) saw the run pause ``runtime_failed``
after three refused Stops.

The answer here is the platform's, never the agent's word:

- **device** (:func:`device_copy_empty`): the run's base commit has Git's empty tree — the base is the empty tree
  itself (``context.repository_empty``) or the server's working copy of the run (``context.local_path``, prepared
  again through the provider's prepare tool when it is gone, e.g. after a restart) resolves the base to it —
  **and** the launcher's Stop facts for this pass (``context.device_change``, launcher code, not the model) show
  the device folder against that same base with an empty patch, untracked files included;
- **server** (:func:`server_copy_empty`): the run's own working copy lists no file, tracked or untracked (ignored
  files are no repository content).

Anything unknown — no server copy, the device lacks the base, no facts for this pass, a truncated patch — is
``False``: the check stays.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ....models import WorkflowRun
from .. import safe_git


def _local_copy(run: WorkflowRun) -> Path | None:
    local = str(dict(run.context or {}).get("local_path") or "")
    return Path(local) if local and (Path(local) / ".git").exists() else None


async def _restored_copy(db: Any, run: WorkflowRun) -> Path | None:
    """The run's server working copy prepared again through its provider's prepare tool (its own connection), when
    the one ``scm.create_branch`` made is gone.

    Without it, after a deploy restart a run's copy was gone, so the
    empty-repository rule never applied and "Run the phase again" paused again. Any failure: ``None`` (unknown)."""
    import logging

    from ..platform.repo_ref import TOOLS, parse_repository
    from ..platform.scm import dispatch_tool

    if db is None:
        return None
    ref = parse_repository(getattr(run, "repository", None))
    if ref is None or not getattr(run, "branch", None) or ref.provider not in TOOLS:
        return None
    try:
        prepared = await dispatch_tool(db, run, TOOLS[ref.provider]["prepare"],
                                       {**ref.args(), "branch_name": run.branch}, capability_class="change")
    except Exception:  # noqa: BLE001 - unknown stays unknown: the check behaves
        logging.getLogger(__name__).warning("empty_copy.restore_failed run_id=%s", run.id, exc_info=True)
        return None
    local = str(prepared.result.get("local_path") or "") if prepared.ok else ""
    if not local or not (Path(local) / ".git").exists():
        return None
    run.context = {**dict(run.context or {}), "local_path": local}
    return Path(local)


async def base_is_empty(run: WorkflowRun, db: Any = None) -> bool:
    """The run's base commit has no file (Git's empty tree); without the server copy it is prepared again."""
    from ..platform.repo_ref import EMPTY_TREE

    base = str(dict(run.context or {}).get("base_sha") or "")
    if not base:
        return False
    if base == EMPTY_TREE:
        return True  # a repository without any commit (``scm.REPOSITORY_EMPTY_KEY``)
    local = _local_copy(run) or await _restored_copy(db, run)
    return local is not None and await safe_git.tree_of(local, base) == EMPTY_TREE


def _unchanged_on_device(run: WorkflowRun) -> bool:
    """The launcher's Stop facts of the current pass: the device folder equals the run's base."""
    context = dict(run.context or {})
    change = context.get("device_change")
    if not isinstance(change, Mapping):
        return False
    entry = dict(run.node_state or {}).get("entry")
    return (change.get("node_id") == run.current_node_id and entry is not None and change.get("entry") == entry
            and str(change.get("base") or "") == str(context.get("base_sha") or "")
            and change.get("base_unavailable") is False and change.get("truncated") is False
            and isinstance(change.get("patch"), str) and not change["patch"].strip())


async def device_copy_empty(run: WorkflowRun, db: Any = None) -> bool:
    return _unchanged_on_device(run) and await base_is_empty(run, db)


async def server_copy_empty(run: WorkflowRun) -> bool:
    local = _local_copy(run)
    if local is None:
        return False
    code, out, _err = await safe_git.git(local, "ls-files", "--cached", "--others", "--exclude-standard")
    return code == 0 and not out.strip()


async def turn_workspace_empty(db: Any, *, request_analysis: dict[str, Any] | None) -> bool:
    """A server phase turn of a run (chat on the platform): its working copy is the run's own."""
    from ..binding import run_marker

    marker = run_marker(request_analysis)
    if marker is None or marker.get("slice"):
        return False  # chat outside a run, or a slice child in its own worktree
    run = await db.get(WorkflowRun, str(marker["run_id"]))
    return run is not None and await server_copy_empty(run)


def asks_for_reads(checks: Sequence[Any]) -> bool:
    """Whether any check would use the answer (so no git runs for a phase without a read check)."""
    from ...workflow_checks.library import read_only_tool_check

    return any(isinstance(check, Mapping) and read_only_tool_check(check) for check in checks)


__all__ = ["asks_for_reads", "base_is_empty", "device_copy_empty", "server_copy_empty", "turn_workspace_empty"]
