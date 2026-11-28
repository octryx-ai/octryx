"""Whether the platform knows a run's working copy holds no file at all (an empty repository)."""

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
    from ..platform.repo_ref import EMPTY_TREE

    base = str(dict(run.context or {}).get("base_sha") or "")
    if not base:
        return False
    if base == EMPTY_TREE:
        return True
    local = _local_copy(run) or await _restored_copy(db, run)
    return local is not None and await safe_git.tree_of(local, base) == EMPTY_TREE


def _unchanged_on_device(run: WorkflowRun) -> bool:
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
    from ..binding import run_marker

    marker = run_marker(request_analysis)
    if marker is None or marker.get("slice"):
        return False
    run = await db.get(WorkflowRun, str(marker["run_id"]))
    return run is not None and await server_copy_empty(run)


def asks_for_reads(checks: Sequence[Any]) -> bool:
    from ...workflow_checks.library import read_only_tool_check

    return any(isinstance(check, Mapping) and read_only_tool_check(check) for check in checks)


__all__ = ["asks_for_reads", "base_is_empty", "device_copy_empty", "server_copy_empty", "turn_workspace_empty"]
