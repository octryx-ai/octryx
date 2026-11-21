"""Successive runs on one Work item.

The common case first: an aborted run left an empty branch (head = main); the next run adopts it instead of blocking
at "Branch already exists". Then: foreign commits pause with a choice, the reason of an abort is recorded, a transient
platform failure pauses and a retry succeeds, a non-recoverable one still ends blocked, one active run per item and
workflow, an earlier open pull request is reused (or refuses on another branch), the change plan of the same contract
is adopted, and the definition must route every failure.
"""

from __future__ import annotations

import pytest

from app.services.workflow_runs.actions import available_actions, perform_action
from app.services.workflow_runs.records import WorkflowRunError
from app.services.workflow_runs.views import run_row, run_view
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.workflow_run_succession_support import (
    BRANCH,
    EXISTS,
    Tools,
    _git,
    _item,
    _name,
    _origin,
    _remote_branch,
    _start,
)


@pytest.mark.asyncio
async def test_the_live_case_an_aborted_runs_empty_branch_is_adopted_by_the_next_run(db, monkeypatch, tmp_path):
    seed, work = _origin(tmp_path)
    tools = Tools(monkeypatch, {"create_github_branch": [{"status": "created"}],
                                "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    key = await publish_phased(db, BRANCH)
    item = await _item(db)
    first = await _start(db, key, item)
    assert (first.status, first.branch) == ("waiting", _name(item))
    _remote_branch(seed, work, _name(item))  # what the provider now has: head = main, no commits
    admin = await admin_user(db)
    await perform_action(db, first, user=admin, body={"action": "abort", "reason": "Restart with the new definition"})
    assert first.status == "stopped" and first.context["stop"]["reason"] == "Restart with the new definition"
    assert run_row(first)["stop_reason"] == "Restart with the new definition"  # the Work item's run list shows it

    tools.answers["create_github_branch"] = [EXISTS]
    second = await _start(db, key, item)
    assert (second.status, second.branch) == ("waiting", _name(item)), second.context.get("actions")
    adoption = second.context["branch_adoption"]
    assert (adoption["from_runs"], adoption["commits"], adoption["decided_by"]) == ([first.id], [], None)
    assert (await run_view(db, second, access="write", user=admin))["adopted"]["branch"]["from_runs"] == [first.id]
    assert tools.tools().count("create_github_branch") == 2


@pytest.mark.asyncio
async def test_a_branch_with_only_earlier_runs_commits_is_adopted_on_those_commits(db, monkeypatch, tmp_path):
    seed, work = _origin(tmp_path)
    Tools(monkeypatch, {"create_github_branch": [{"status": "created"}],
                        "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    key = await publish_phased(db, BRANCH)
    item = await _item(db)
    first = await _start(db, key, item)
    pushed = _remote_branch(seed, work, _name(item), foreign_commit=True)
    first.context = {**first.context, "pushed_commits": [pushed]}  # the earlier run pushed this commit
    await perform_action(db, first, user=await admin_user(db), body={"action": "abort", "reason": "retry"})
    scm_tools = Tools(monkeypatch, {"create_github_branch": [EXISTS],
                                    "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    second = await _start(db, key, item)
    assert second.status == "waiting" and second.context["branch_adoption"]["commits"] == [pushed]
    assert _git(work, "rev-parse", "HEAD") == pushed  # the working copy starts from the adopted commits
    assert second.context["base_sha"] == _git(work, "rev-parse", "origin/main")  # reviewed against the base
    assert "create_github_branch" in scm_tools.tools()


@pytest.mark.asyncio
async def test_foreign_commits_pause_with_adopt_new_name_or_abort(db, monkeypatch, tmp_path):
    seed, work = _origin(tmp_path)
    tools = Tools(monkeypatch, {"create_github_branch": [{"status": "created"}],
                                "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    key = await publish_phased(db, BRANCH)
    item = await _item(db)
    admin = await admin_user(db)
    first = await _start(db, key, item)
    await perform_action(db, first, user=admin, body={"action": "abort", "reason": "retry"})
    head = _remote_branch(seed, work, _name(item), foreign_commit=True)  # someone pushed onto it meanwhile

    tools.answers["create_github_branch"] = [EXISTS]
    second = await _start(db, key, item)
    assert (second.status, second.pause_reason) == ("paused", "action_failed")
    failure = second.node_state["pause"]["failure"]
    assert failure["failure_class"] == "branch_conflict" and failure["detail"]["foreign_commits"] == [head]
    keys = [action["key"] for action in await available_actions(db, second, access="write", user=admin)]
    assert keys[:3] == ["retry_action", "adopt_branch", "new_branch"] and "abort" in keys
    view = await run_view(db, second, access="write", user=admin)
    assert view["pause"]["failed_action"]["failure_class"] == "branch_conflict"

    with pytest.raises(WorkflowRunError):
        await perform_action(db, second, user=admin, body={"action": "new_branch", "branch": "../bad"})
    tools.answers["create_github_branch"] = [{"status": "created"}]
    await perform_action(db, second, user=admin, body={"action": "new_branch", "branch": f"{_name(item)}-2"})
    assert (second.status, second.branch) == ("waiting", f"{_name(item)}-2")
    assert tools.calls[-2] == ("create_github_branch", {"repository": "acme/payments",
                                                        "branch_name": f"{_name(item)}-2"})

    third_item = await _item(db)
    third = await _start(db, key, third_item)  # a branch that no earlier run of this item created
    await perform_action(db, third, user=admin, body={"action": "abort", "reason": "retry"})
    tools.answers["create_github_branch"] = [EXISTS]
    _remote_branch(seed, work, _name(third_item), foreign_commit=True)
    fourth = await _start(db, key, third_item)
    assert fourth.pause_reason == "action_failed"
    tools.answers["create_github_branch"] = [EXISTS]
    await perform_action(db, fourth, user=admin, body={"action": "adopt_branch"})
    assert fourth.status == "waiting" and fourth.context["branch_adoption"]["decided_by"] == admin.id


@pytest.mark.asyncio
async def test_no_earlier_run_created_the_branch_so_only_an_empty_one_is_adopted_silently(db, monkeypatch, tmp_path):
    """A crashed run created the branch at main and never recorded it. An empty branch carries
    nobody's work, so it is adopted; one with a commit nobody of this item pushed is a conflict."""
    seed, work = _origin(tmp_path)
    Tools(monkeypatch, {"create_github_branch": [EXISTS],
                        "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    key = await publish_phased(db, BRANCH)
    item = await _item(db)
    _remote_branch(seed, work, _name(item))  # empty, and nobody of this item made it
    run = await _start(db, key, item)
    assert (run.status, run.branch) == ("waiting", _name(item))
    assert (run.context["branch_adoption"]["from_runs"], run.context["branch_adoption"]["commits"]) == ([], [])

    other = await _item(db)
    _remote_branch(seed, work, _name(other), foreign_commit=True)
    refused = await _start(db, key, other)
    assert refused.pause_reason == "action_failed"
    assert "no earlier run of this Work item created it" in refused.node_state["pause"]["message"]
