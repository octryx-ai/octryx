"""An existing remote branch at ``scm.create_branch``: adopt it only when it is this Work item's own.

The remote branch already exists when creating it failed and the prepared working copy (whose ``git fetch --prune``
read every remote branch) has ``origin/<name>``. The run adopts it silently only when

1. it is **empty**: no commit its base lacks (it points at the expected base, or behind it) — nobody's work is on
   it, whoever created it (e.g. a crashed run created it and never recorded it); or
2. an earlier run of the **same Work item** on the same repository recorded it as the branch the platform created
   (``context.branch_created`` or ``branch``), and every commit on it that its base does not have is one an earlier
   run of this item pushed (``context.pushed_commits`` / ``head_sha``).

Otherwise the action fails ``branch_conflict`` with the facts (who created it, the foreign commits, the remote head):
a pause node lets the requester adopt it anyway (bound to the head they were shown), name a new branch, or abort. An
adopted branch with commits becomes the working copy's starting point (``origin/<name>``), never the base.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from .. import safe_git
from ..records import record_event
from .dispatch import CLASS_BRANCH_CONFLICT, FAILED, SUCCEEDED, ToolOutcome

EVENT_ADOPTED = "branch_adopted"
MAX_LISTED = 20


async def remote_head(local_path: str, name: str) -> str:
    code, out, _err = await safe_git.git(local_path, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}")
    return out.strip() if code == 0 else ""


async def own_commits(local_path: str, name: str, base_branch: str) -> list[str] | None:
    """The branch's commits its base lacks (oldest first); ``None`` when git cannot tell."""
    base = f"refs/remotes/origin/{base_branch}" if base_branch else "refs/remotes/origin/HEAD"
    code, out, _err = await safe_git.git(local_path, "rev-list", "--reverse", f"refs/remotes/origin/{name}",
                                         "--not", base)
    return out.split() if code == 0 else None


def pushed_by(runs: list[WorkflowRun]) -> set[str]:
    commits: set[str] = set()
    for run in runs:
        context = dict(run.context or {})
        commits.update(str(sha) for sha in context.get("pushed_commits") or [] if sha)
        if context.get("head_sha"):
            commits.add(str(context["head_sha"]))
    return commits


def created_by(runs: list[WorkflowRun], name: str) -> list[WorkflowRun]:
    return [run for run in runs if name in (str(dict(run.context or {}).get("branch_created") or ""), run.branch)]


async def existing_branch(db: AsyncSession, run: WorkflowRun, name: str, prepared: ToolOutcome) -> ToolOutcome | None:
    """``None``: the remote branch does not exist (the create failure stands); else adopted or ``branch_conflict``."""
    from ..succession import earlier_runs

    local_path = str(prepared.result.get("local_path") or "")
    head = await remote_head(local_path, name) if local_path else ""
    if not head:
        return None
    # A chained story's branch starts from the story before it (``epic_chain``): the commits of that base are not the
    # branch's own (otherwise the spec commit counted as foreign: branch_conflict).
    chain_base = str(dict(run.context or {}).get("base_branch") or "").strip()
    base = chain_base or str(prepared.result.get("base_branch") or "")
    commits = await own_commits(local_path, name, base)
    earlier = await earlier_runs(db, run)
    owners = created_by(earlier, name)
    foreign = [sha for sha in (commits or []) if sha not in pushed_by(owners)]
    confirmed = dict(dict(run.context or {}).get("branch_adoption_confirmed") or {})
    by_person = confirmed.get("branch") == name and confirmed.get("head") == head
    # An empty branch (no commit its base lacks: it points at the expected base) carries nobody's work: adopting it
    # loses nothing, whoever created it. Otherwise a first run that created the branch
    # at main and crashed before recording it left the next run's create answering 400 "already
    # exists" and could never go on.
    empty = commits == []
    if not by_person and not empty and (not owners or commits is None or foreign):
        why = ("no earlier run of this Work item created it" if not owners else
               "git could not list its commits" if commits is None else
               f"it has {len(foreign)} commit(s) no earlier run of this Work item pushed")
        conflict = {"branch": name, "remote_head": head, "created_by_runs": [item.id for item in owners],
                    "foreign_commits": foreign[:MAX_LISTED], "commit_count": len(commits or [])}
        return ToolOutcome(FAILED, {"conflict": conflict}, f"The branch {name} already exists and {why}.",
                           failure_class=CLASS_BRANCH_CONFLICT)
    adoption = {"branch": name, "head": head, "commits": (commits or [])[:MAX_LISTED],
                "from_runs": [item.id for item in owners], "decided_by": confirmed.get("by") if by_person else None,
                "foreign_commits": foreign[:MAX_LISTED]}
    run.context = {**dict(run.context or {}), "branch_created": name, "branch_adoption": adoption}
    record_event(db, run, EVENT_ADOPTED, node_id=run.current_node_id, detail=adoption)
    return ToolOutcome(SUCCEEDED, {**prepared.result, "status": "adopted", "branch": name})


async def start_from_adopted(run: WorkflowRun, local_path: str, name: str) -> str:
    """Put the working copy on the adopted branch's commits; '' or why it could not."""
    context = dict(run.context or {})
    adoption = dict(context.get("branch_adoption") or {})
    # A story of an epic: its branch starts from the story before it (``epic_chain``, ``base_branch``), so the
    # working copy takes the remote branch as it is, not the default branch (otherwise the copy started from
    # master, the remote branch from the spec, and the push was refused as non-fast-forward).
    chained = bool(str(context.get("base_branch") or "").strip())
    if not chained and (adoption.get("branch") != name or not adoption.get("commits")):
        return ""
    if chained and (await safe_git.git(local_path, "rev-parse", "--verify", "--quiet",
                                       f"refs/remotes/origin/{name}"))[0] != 0:
        return ""  # the branch is not on the remote yet: the run's first push creates it
    code, _out, err = await safe_git.git(local_path, "checkout", "-q", "-B", name, f"refs/remotes/origin/{name}")
    return "" if code == 0 else (err.strip() or "git checkout of the adopted branch failed")[:300]


__all__ = ["EVENT_ADOPTED", "existing_branch", "own_commits", "remote_head", "start_from_adopted"]
