"""An earlier run's pull request at ``scm.open_pr``: one Work item, at most one open pull request.

Before opening a pull request the run reads (on the provider, never from its records alone) every pull request an
earlier run of the same Work item recorded on the same repository (its stored identity: host, path and number; read
only through a connection on that host, ``read_recorded_pull_request``):

- still open on the run's branch → **reused**: recorded on this run with the run it came from (``adopted_from_run``);
- still open on another branch (the requester chose a new branch name) → the step fails ``pr_conflict``: the person
  closes it in the SCM (an explicit act) and retries, so no second open pull request appears;
- merged or declined → not adopted; this run opens its own;
- unreadable → the step fails with the read's failure class (a transient read never duplicates a pull request).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..records import record_event
from .dispatch import CLASS_PR_CONFLICT, FAILED, SUCCEEDED, ToolOutcome, dispatch_tool

EVENT_ADOPTED = "pull_request_adopted"
_NUMBER_KEYS = {"github": "pr_number", "gitlab": "mr_iid", "bitbucket": "pr_id"}


async def read_recorded_pull_request(db: AsyncSession, run: WorkflowRun, identity: dict[str, str]
                                     ) -> ToolOutcome | None:
    """The provider's answer for the pull request of the stored ``identity`` (``record_identity.stored_identity``),
    read through the governed read tool on the connection the run's Workspace routes its repository to; ``None``
    when that connection is not on the recorded host: the pull request is then not read at all, so another host's
    pull request with the same path and number is never taken for it."""
    from ...secure_work.pull_requests.host_target import connection_host
    from .bitbucket_cloud import serving_config
    from .repo_ref import TOOLS, RepoRef

    ref = RepoRef(identity["provider"], f"{identity['project_key']}/{identity['repository_slug']}")
    tool = TOOLS[ref.provider]["get_pr"]
    served = await serving_config(db, run, ref.args(), tool_name=tool)
    if connection_host(ref.provider, served) != identity["provider_instance"]:
        return None
    return await dispatch_tool(db, run, tool, {**ref.args(), _NUMBER_KEYS[ref.provider]: identity["pr_id"]},
                               capability_class="read_only")


async def earlier_pull_request(db: AsyncSession, run: WorkflowRun, ref: Any) -> ToolOutcome | None:
    """``None``: no earlier open pull request, open one; else the reused one or why the step refuses.

    An earlier run's pull request is its stored identity on the run's repository; one recorded on another host than
    the repository's connection now serves is another repository's and is never adopted or blocking."""
    from ...secure_work.pull_requests.record_identity import stored_identity
    from ..succession import earlier_runs
    from ..watch import PR_DECLINED, PR_MERGED, pr_condition

    seen: set[tuple[str, ...]] = set()
    for earlier in await earlier_runs(db, run):
        pr = dict(earlier.pull_request or {})
        identity = stored_identity(pr)
        if identity is None or (identity["provider"], f"{identity['project_key']}/{identity['repository_slug']}") != (
                ref.provider, ref.path) or tuple(identity.values()) in seen:
            continue
        seen.add(tuple(identity.values()))
        number = identity["pr_id"]
        read = await read_recorded_pull_request(db, run, identity)
        if read is None:
            continue
        if not read.ok:
            return ToolOutcome(FAILED, read.result, f"the open state of pull request #{number} of an earlier run "
                                                    f"could not be read: {read.reason}",
                               failure_class=read.failure_class)
        if pr_condition(ref.provider, read.result) in (PR_MERGED, PR_DECLINED):
            continue
        if pr.get("branch") != run.branch:
            return ToolOutcome(FAILED, {"conflict": {"pull_request": pr, "run_id": earlier.id}},
                               f"Pull request #{number} of run {earlier.id} (branch {pr.get('branch')}) is still open: "
                               "close it in the SCM, then retry — a Work item has one open pull request.",
                               failure_class=CLASS_PR_CONFLICT)
        run.pull_request = {**pr, "state": "open", "adopted_from_run": earlier.id}
        record_event(db, run, EVENT_ADOPTED, node_id=run.current_node_id,
                     detail={"pull_request": number, "from_run": earlier.id, "branch": run.branch})
        return ToolOutcome(SUCCEEDED, {"status": "adopted", **run.pull_request})
    return None


__all__ = ["EVENT_ADOPTED", "earlier_pull_request", "read_recorded_pull_request"]
