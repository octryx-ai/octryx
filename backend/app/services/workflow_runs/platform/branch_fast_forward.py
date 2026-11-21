"""An adopted branch without own commits starts at the current default-branch head.

Without it, an adopted ``feature/-…`` branch stayed at an old commit while main had moved on (a ``.gitignore``
commit): the run worked on an outdated base. At ``scm.create_branch``, after ``branch_adoption`` adopted an existing
branch, before ``workspace.prepare``:

- **no own commits** (every commit on it is on the default branch) and the default branch is ahead → the remote
  branch is fast-forwarded to the default-branch head on the server: the prepared working copy puts the branch on
  ``origin/<default>`` and the provider's governed push tool pushes it without a commit (``push_only``; a plain,
  never forced push — the SCM itself refuses anything but a fast-forward), on every provider. Recorded as
  ``branch_fast_forwarded`` with the old and new head; the adoption's head becomes the new one, so every runtime
  prepares that commit. A push that fails fails the step (recoverable: retry);
- **own commits** → the branch is never moved; how many default-branch commits it lacks is recorded on the adoption
  (``behind_base``) and shown on the run card.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from .. import safe_git
from ..records import record_event
from . import dispatch
from .dispatch import CLASS_EXTERNAL, FAILED, ToolOutcome

EVENT_FAST_FORWARDED = "branch_fast_forwarded"


async def _rev(local_path: str, ref: str) -> str:
    code, out, _err = await safe_git.git(local_path, "rev-parse", "--verify", "--quiet", ref)
    return out.strip() if code == 0 else ""


async def _behind(local_path: str, name: str, base: str) -> int | None:
    code, out, _err = await safe_git.git(local_path, "rev-list", "--count",
                                         f"refs/remotes/origin/{name}..refs/remotes/origin/{base}")
    return int(out.strip()) if code == 0 and out.strip().isdigit() else None


async def align_adopted_branch(db: AsyncSession, run: WorkflowRun, *, push_tool: str, repo_args: dict[str, Any],
                               name: str, prepared: ToolOutcome) -> ToolOutcome | None:
    """Fast-forward an adopted branch without own commits; ``None`` unless that push failed."""
    context = dict(run.context or {})
    adoption = dict(context.get("branch_adoption") or {})
    local_path = str(prepared.result.get("local_path") or "")
    base_branch = str(prepared.result.get("base_branch") or "") or "HEAD"
    if adoption.get("branch") != name or not local_path:
        return None
    base_ref = f"refs/remotes/origin/{base_branch}"
    old, new = await _rev(local_path, f"refs/remotes/origin/{name}"), await _rev(local_path, base_ref)
    if adoption.get("commits"):
        behind = await _behind(local_path, name, base_branch)
        run.context = {**context, "branch_adoption": {**adoption, "behind_base": behind, "base_branch": base_branch}}
        return None  # a branch with its own commits is never moved
    if not old or not new or old == new:
        return None
    code, _out, _err = await safe_git.git(local_path, "merge-base", "--is-ancestor", old, new)
    if code != 0:
        return None  # not a fast-forward (cannot happen without own commits; never forced)
    _code, status, _err = await safe_git.git(local_path, "status", "--porcelain")
    if status.strip():
        return ToolOutcome(FAILED, reason="the server working copy has uncommitted changes; the adopted branch was "
                                          "not fast-forwarded", failure_class=CLASS_EXTERNAL)
    code, _out, err = await safe_git.git(local_path, "checkout", "-q", "-B", name, base_ref)
    if code != 0:
        return ToolOutcome(FAILED, reason=f"git checkout for the fast-forward failed: {err.strip()[:200]}",
                           failure_class=CLASS_EXTERNAL)
    pushed = await dispatch.dispatch_tool(db, run, push_tool, {
        **repo_args, "local_path": local_path, "branch_name": name, "push_only": True,
        "commit_message": f"fast-forward {name} to {base_branch}"}, capability_class="deliver",
        workspace_root=local_path)  # the copy just prepared (not yet the run's recorded one) is the root
    if not pushed.ok:
        return ToolOutcome(FAILED, pushed.result, f"the adopted branch {name} could not be fast-forwarded to "
                                                  f"{base_branch}: {pushed.reason}", failure_class=CLASS_EXTERNAL)
    detail = {"branch": name, "old": old, "new": new, "base_branch": base_branch}
    run.context = {**context, "branch_adoption": {**adoption, "head": new, "fast_forwarded_from": old,
                                                           "base_branch": base_branch},
                   "branch_fast_forwarded": detail}
    record_event(db, run, EVENT_FAST_FORWARDED, node_id=run.current_node_id, detail=detail)
    return None


__all__ = ["EVENT_FAST_FORWARDED", "align_adopted_branch"]
