"""Source-control platform actions of a run: branch, push, pull request."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.runtime.secure_work import WorkItem
from .. import safe_git
from . import branch_adoption
from .dispatch import (
    CLASS_EXTERNAL,
    CLASS_INVALID,
    CLASS_NEEDS_FIX,
    CLASS_SAFETY,
    FAILED,
    SUCCEEDED,
    ToolOutcome,
    dispatch_tool,
)
from .pr_details import (
    _bounded_description,
    _no_pr_target,
    _pr_description,
    _pr_target,
    _record_opened,
    open_findings_text,
    review_notes_text,
    run_links,
)
from .repo_ref import (
    REPOSITORY_EMPTY_KEY,
    TOOLS,
    RepoRef,
    _no_repository,
    _not_found,
    ai_trailers,
    branch_name,
    parse_repository,
    reviewers_for,
    run_models,
    work_key,
)
from .working_copy_git import (
    _already_pushed,
    _head_commit,
    _merge_base,
    _on_branch,
    _record_pushed,
    _record_spec,
    _review_now,
    _reviewed_tree,
)


async def create_branch(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    ref = parse_repository(run.repository)
    if ref is None:
        return _no_repository(run)
    if not work_key(run, await db.get(WorkItem, run.work_item_id) if run.work_item_id else None):
        return ToolOutcome(FAILED, reason="a branch is named from the ticket key; the run has no ticket")
    if run.branch and dict(run.context or {}).get("local_path"):
        # The run already created its branch and working copy: never a second branch.
        return ToolOutcome(SUCCEEDED, {"status": "existing", "branch": run.branch})
    context = dict(run.context or {})
    # A new name the requester chose at a branch conflict comes first.
    name = str(context.get("branch_override") or "") or run.branch or str(context.get("branch_created") or "") or (
        await branch_name(db, run, ref, str(params.get("branch_type") or "feature")))
    prepare_args = {**ref.args(), "branch_name": name}
    if context.get("branch_created") != name:
        base = str(context.get("base_branch") or "").strip()
        created = await dispatch_tool(db, run, TOOLS[ref.provider]["branch"],
                                      {**ref.args(), "branch_name": name, **({"start_point": base} if base else {})},
                                      capability_class="deliver")
        if created.state == FAILED and base and _not_found(created):
            # The story before it was merged and its branch deleted: the default branch now holds that work.
            from ..records import record_event

            run.context = {key: value for key, value in dict(run.context or {}).items() if key != "base_branch"}
            record_event(db, run, "base_branch_gone", node_id=run.current_node_id, detail={"base_branch": base})
            created = await dispatch_tool(db, run, TOOLS[ref.provider]["branch"], {**ref.args(), "branch_name": name},
                                          capability_class="deliver")
        if created.state == FAILED:
            prepared = await dispatch_tool(db, run, TOOLS[ref.provider]["prepare"], prepare_args,
                                           capability_class="change")
            if prepared.ok and prepared.result.get(REPOSITORY_EMPTY_KEY) is True:
                # No commit yet: the branch is created by the run's first push.
                run.context = {**dict(run.context or {}), REPOSITORY_EMPTY_KEY: True}
                return await _on_branch(db, run, ref, name, prepared)
            existing = await branch_adoption.existing_branch(db, run, name, prepared) if prepared.ok else None
            if existing is None:
                return created
            return await _on_branch(db, run, ref, name, prepared) if existing.ok else existing
        if not created.ok:
            return created
        # Recorded at once: when preparing the working copy fails or waits for an approval, the rerun only
        # prepares — the remote branch is never created twice.
        run.context = {**dict(run.context or {}), "branch_created": name}
    prepared = await dispatch_tool(db, run, TOOLS[ref.provider]["prepare"], prepare_args, capability_class="change")
    return await _on_branch(db, run, ref, name, prepared) if prepared.ok else prepared


async def checkout(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    ref = parse_repository(run.repository)
    if ref is None:
        return _no_repository(run)
    if not run.branch:
        return ToolOutcome(FAILED, reason="a review needs the branch to review (the run's branch)")
    # ``review_only`` (the PR review bot): the copy is only read, so the repository's ``read`` operation suffices; the
    # local branch is never pushed (a read+pr repository would otherwise refuse ``branch``).
    review_only = {"review_only": True} if params.get("review_only") is True else {}
    prepared = await dispatch_tool(db, run, TOOLS[ref.provider]["prepare"],
                                   {**ref.args(), "branch_name": run.branch, **review_only}, capability_class="change")
    if not prepared.ok:
        return prepared
    local_path = str(prepared.result.get("local_path") or "")
    # The prepare tool sets the named branch up from the base branch (right for a new branch); a review needs the
    # existing branch as it is on the remote, else the change under review is empty.
    remote = f"origin/{run.branch}"
    if (await safe_git.git(local_path, "rev-parse", "--verify", "--quiet", f"{remote}^{{commit}}"))[0] != 0:
        return ToolOutcome(FAILED, reason=f"the branch '{run.branch}' to review is not on the remote",
                           failure_class=CLASS_INVALID)
    if (await safe_git.git(local_path, "checkout", "-q", "-B", run.branch, remote))[0] != 0:
        return ToolOutcome(FAILED, reason=f"the branch '{run.branch}' could not be checked out",
                           failure_class=CLASS_EXTERNAL)
    base_branch = str(params.get("base_branch") or "").strip() or "HEAD"
    base = await _merge_base(local_path, base_branch)
    run.context = {**dict(run.context or {}), "local_path": local_path, "base_sha": base}
    return ToolOutcome(SUCCEEDED, {"local_path": local_path, "base_sha": base})


async def push(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    del params
    ref = parse_repository(run.repository)
    local_path = str(dict(run.context or {}).get("local_path") or "")
    if ref is None:
        return _no_repository(run)
    if not run.branch or not local_path:
        return ToolOutcome(FAILED, reason="push needs the run's branch and working copy (create the branch first)")
    from ..spec_studio.hooks import before_push

    await before_push(db, run)
    reviewed = await _reviewed_tree(db, run, local_path)
    if isinstance(reviewed, ToolOutcome):
        return reviewed
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    message = f"{work_key(run, item)}: {item.title if item is not None else run.title}".strip(": ")
    # A run without a Work item may name what its commit does (the PR review bot's fix run: the findings and the
    # pull request, ``pr_review_bot.fix``); the trailers stay last.
    body = str(dict(run.context or {}).get("commit_body") or "").strip()
    message = f"{message}\n\n{body}" if body and item is None else message
    message = f"{message}\n\n{ai_trailers(run, item, await run_models(db, run))}"
    outcome = await dispatch_tool(db, run, TOOLS[ref.provider]["push"], {
        **ref.args(), "local_path": local_path, "commit_message": message, "branch_name": run.branch,
    }, capability_class="deliver")
    if outcome.ok and outcome.result.get("status") == "no_changes":
        from ..ci_return import pending_ci_failure

        if pending_ci_failure(run) is not None:
            return ToolOutcome(FAILED, outcome.result, "nothing to push: the CI failure of the pushed commit is not "
                                                       "fixed yet", failure_class=CLASS_NEEDS_FIX)
        if await _already_pushed(local_path, run, str(outcome.result.get("head_commit") or "")):
            # A retried push can find the commit made and pushed by an earlier
            # attempt; "nothing to push" must not end the run blocked when the branch carries the reviewed change.
            # Recorded like a push (head, pushed commits): the next run of the Work item adopts it as the run's own.
            head = await _head_commit(local_path)
            _record_pushed(run, head)
            await _record_spec(run, local_path, head)
            return ToolOutcome(SUCCEEDED, {**outcome.result, "status": "already_pushed", "head_commit": head})
        return ToolOutcome(FAILED, outcome.result, "nothing to push: the working copy has no change")
    if outcome.ok:
        # CI is judged on this commit only: an earlier round's (or another commit's) result never counts.
        head = str(outcome.result.get("head_commit") or "") or await _head_commit(local_path)
        if reviewed and await safe_git.tree_of(local_path, head or "HEAD") != reviewed:
            run.context = {**dict(run.context or {}), "push_mismatch": {"head_sha": head, "reviewed_tree": reviewed}}
            return ToolOutcome(FAILED, outcome.result, "the pushed commit is not the change the reviewer reviewed",
                               failure_class=CLASS_SAFETY)
        _record_pushed(run, head)
        await _record_spec(run, local_path, head)
        _review_now(db, run)
    return outcome


async def _existing_github_pr(db: AsyncSession, run: WorkflowRun, ref: RepoRef) -> ToolOutcome | None:
    # A restart between the create call and the commit makes the retry create again, and GitHub then answers 422.
    owner = ref.path.split("/", 1)[0]
    listed = await dispatch_tool(db, run, "list_github_pull_requests", {
        **ref.args(), "state": "open", "head": f"{owner}:{run.branch}"}, capability_class="read_only")
    if not listed.ok:
        return None
    found = [item for item in listed.result.get("pull_requests") or []
             if isinstance(item, dict) and item.get("head_ref") in (run.branch, None) and item.get("number")]
    if len(found) != 1:
        return None
    return ToolOutcome(SUCCEEDED, {"status": "adopted", "number": found[0]["number"],
                                   "html_url": found[0].get("html_url") or ""})


async def open_pr(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    ref = parse_repository(run.repository)
    if ref is None:
        return _no_repository(run)
    if not run.branch:
        return ToolOutcome(FAILED, reason="a pull request needs the run's branch")
    existing = dict(run.pull_request or {})
    if existing.get("id") and existing.get("branch") == run.branch:
        # One pull request per run branch: a repeated step returns the recorded one.
        return ToolOutcome(SUCCEEDED, {"status": "existing", **existing})
    from .pr_adoption import earlier_pull_request

    # An earlier run's open pull request on this branch is reused; one on another branch refuses (never two open).
    earlier = await earlier_pull_request(db, run, ref)
    if earlier is not None:
        return earlier
    chosen = await reviewers_for(db, run, ref)
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    title = f"{work_key(run, item)}: {item.title if item is not None else run.title}".strip(": ")
    chosen, description = await _pr_description(db, run, chosen,
                                                f"{work_key(run, item)} · workflow run {run.id}".strip(" ·"))
    arguments = {**ref.args(), "title": title, "from_branch": run.branch, "reviewers": chosen.names,
                 **({"requester": chosen.requester} if chosen.requester else {}), "description": description}
    target, stacked = await _pr_target(db, run, params)
    if target:
        arguments["to_branch"] = target
    if stacked:
        arguments["description"] = f"{arguments['description']}\n\n{stacked}"
    if notes := review_notes_text(run):
        arguments["description"] = f"{arguments['description']}\n\n{notes}"
    if findings := open_findings_text(run):
        arguments["description"] = f"{findings}\n\n{arguments['description']}"
    from ..red_on_base_proof import evidence_text, unproven

    if why := unproven(run):  # never without the class's base-commit proof
        return ToolOutcome(FAILED, reason=f"the pull request waits: {why}")
    if proof := evidence_text(run):
        arguments["description"] = f"{arguments['description']}\n\n{proof}"
    arguments["description"] = _bounded_description(arguments["description"], run, await run_links(db, run))
    outcome = await dispatch_tool(db, run, TOOLS[ref.provider]["pr"], arguments, capability_class="deliver")
    if not outcome.ok and outcome.state == FAILED and dict(run.context or {}).get(REPOSITORY_EMPTY_KEY):
        return _no_pr_target(run, outcome)
    if not outcome.ok and ref.provider == "github" and "already exists" in f"{outcome.reason} {outcome.result}".lower():
        outcome = await _existing_github_pr(db, run, ref) or outcome
    if not outcome.ok:
        return outcome
    await _record_opened(db, run, ref, chosen, outcome, item, title)
    _review_now(db, run)
    return ToolOutcome(SUCCEEDED, outcome.result)


__all__ = ["checkout", "create_branch", "open_pr", "push"]
