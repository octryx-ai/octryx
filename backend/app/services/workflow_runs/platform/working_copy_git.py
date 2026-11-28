"""The run's working copy in git: its branch, merge base and head, and what is already pushed and reviewed."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from .. import safe_git
from . import branch_adoption, branch_fast_forward
from .dispatch import CLASS_EXTERNAL, CLASS_SAFETY, FAILED, ToolOutcome
from .repo_ref import EMPTY_TREE, REPOSITORY_EMPTY_KEY, TOOLS, RepoRef

logger = logging.getLogger(__name__)


async def _on_branch(db: AsyncSession, run: WorkflowRun, ref: RepoRef, name: str,
                     prepared: ToolOutcome) -> ToolOutcome:
    local_path = str(prepared.result.get("local_path") or "")
    failed = await branch_adoption.start_from_adopted(run, local_path, name) if local_path else ""
    if failed:
        return ToolOutcome(FAILED, prepared.result, failed, failure_class=CLASS_EXTERNAL)
    aligned = await branch_fast_forward.align_adopted_branch(db, run, push_tool=TOOLS[ref.provider]["push"],
                                                             repo_args=ref.args(), name=name, prepared=prepared)
    if aligned is not None:
        return aligned
    run.branch = name
    context = dict(run.context or {})
    context["local_path"] = local_path
    # The commit the run's change starts from: the independent reviewer reviews the diff against it; on an
    # adopted branch with commits the merge base, so the earlier runs' commits are reviewed as well.
    if local_path and dict(context.get("branch_adoption") or {}).get("commits"):
        # A chained story measures against the story before it, not main.
        chained = str(context.get("base_branch") or "").strip()
        base = await _merge_base(local_path, chained or str(prepared.result.get("base_branch") or "") or "HEAD")
    else:
        base = await _head_commit(local_path) if local_path else ""
    if not base and context.get(REPOSITORY_EMPTY_KEY):
        base = EMPTY_TREE
    context.setdefault("base_sha", base)
    run.context = context
    return prepared


async def _merge_base(local_path: str, base_branch: str) -> str:
    import asyncio

    target = f"origin/{base_branch}" if base_branch != "HEAD" else "origin/HEAD"
    try:
        process = await asyncio.create_subprocess_exec(
            "git", "merge-base", "HEAD", target, cwd=local_path, env=safe_git.git_env(), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        stdout, _ = await process.communicate()
    except OSError:
        return ""
    return stdout.decode().strip() if process.returncode == 0 else ""


async def _already_pushed(local_path: str, run: WorkflowRun, pushed_head: str = "") -> bool:
    # Bitbucket Cloud pushes to the clone URL, which never moves refs/remotes/origin/<branch>.
    context = dict(run.context or {})
    head = (await safe_git.git(local_path, "rev-parse", "HEAD"))[1].strip()
    remote = await safe_git.git(local_path, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{run.branch}")
    on_remote = (remote[0] == 0 and remote[1].strip() == head) or (bool(pushed_head) and pushed_head == head)
    if not head or not on_remote or head == str(context.get("base_sha") or ""):
        return False
    base_branch = str(context.get("base_branch") or "").strip()
    if base_branch:
        inside = await safe_git.git(local_path, "merge-base", "--is-ancestor", "HEAD",
                                    f"refs/remotes/origin/{base_branch}")
        return inside[0] != 0
    return True


def _review_now(db: AsyncSession, run: WorkflowRun) -> None:
    from ...pr_review_bot.instant import head_ready

    head_ready(db, run)


async def _record_spec(run: WorkflowRun, local_path: str, head: str) -> None:
    from ..review.spec_commit import record_spec_commit

    try:
        await record_spec_commit(run, local_path, head)
    except Exception:  # noqa: BLE001 - without the record the review falls back to the spec's git history
        logger.warning("spec commit not recorded for run %s", run.id, exc_info=True)


def _record_pushed(run: WorkflowRun, head: str) -> None:
    context = dict(run.context or {})
    context.pop("ci", None)
    context["head_sha"] = head
    context["pushed_commits"] = list(dict.fromkeys([*(context.get("pushed_commits") or []), head]))[-50:]
    run.context = context


async def _reviewed_tree(db: AsyncSession, run: WorkflowRun, local_path: str) -> str | ToolOutcome:
    # The platform pushes exactly the reviewed tree: checked before the push and on the pushed commit after.
    from ..test_runs import device_run

    tree = str(dict(dict(run.context or {}).get("review") or {}).get("tree") or "")
    if not tree:
        if await device_run(db, run):
            return ToolOutcome(FAILED, reason="a device run pushes only the change the independent reviewer "
                                              "reviewed on the run's branch; this run has none",
                               failure_class=CLASS_SAFETY)
        return ""
    if await safe_git.staged_tree(local_path) != tree:
        return ToolOutcome(FAILED, reason="the working copy is no longer the change the reviewer reviewed",
                           failure_class=CLASS_SAFETY)
    return tree


async def _head_commit(local_path: str) -> str:
    import asyncio

    try:
        process = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD", cwd=local_path, env=safe_git.git_env(), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        stdout, _ = await process.communicate()
    except OSError:
        return ""  # no readable working copy: CI is then judged on the branch
    return stdout.decode().strip() if process.returncode == 0 else ""
