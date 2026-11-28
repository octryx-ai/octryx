"""An adopted branch without own commits is fast-forwarded to the default-branch head before ``workspace.prepare``;
one with its own commits is never moved."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.models import WorkflowRun
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.platform import dispatch as dispatch_module
from app.services.workflow_runs.platform.dispatch import read_outcome
from app.services.workflow_runs.views import run_view
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_acceptance_support import _settle, _workspace, systems  # noqa: F401
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

pytestmark = pytest.mark.usefixtures("scripted_pool")

B_KEY = "feature-delivery-tdd"


def _advance_main(seed: Path, work: Path) -> str:
    _git(seed, "checkout", "-q", "main")
    (seed / ".gitignore").write_text(".venv/\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "ignore the venv")
    _git(seed, "push", "-q", "origin", "main")
    _git(work, "fetch", "-q", "--prune", "origin")
    return _git(seed, "rev-parse", "HEAD")


def _pushing(tools: Tools, monkeypatch) -> None:
    scripted = dispatch_module.dispatch_tool

    async def dispatch(db, run, tool, arguments, *, capability_class, workspace_root=None):
        if arguments.get("push_only"):
            # The push runs in the copy just prepared (the run's root), never the session's folder.
            assert workspace_root == arguments["local_path"]
            tools.calls.append((tool, arguments))
            done = subprocess.run(["git", "push", "origin", arguments["branch_name"]], cwd=arguments["local_path"],
                                  capture_output=True, text=True)
            return read_outcome({"status": "pushed"} if done.returncode == 0 else {"error": done.stderr})
        return await scripted(db, run, tool, arguments, capability_class=capability_class)

    monkeypatch.setattr(dispatch_module, "dispatch_tool", dispatch)


async def _first_run_left(db, monkeypatch, tmp_path, *, own_commit: bool):
    seed, work = _origin(tmp_path)
    Tools(monkeypatch, {"create_github_branch": [{"status": "created"}],
                        "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    key = await publish_phased(db, BRANCH)
    item = await _item(db)
    first = await _start(db, key, item)
    head = _remote_branch(seed, work, _name(item), foreign_commit=own_commit)
    if own_commit:
        first.context = {**first.context, "pushed_commits": [head]}
    await perform_action(db, first, user=await admin_user(db), body={"action": "abort", "reason": "restart"})
    return seed, work, key, item, head


@pytest.mark.asyncio
async def test_an_adopted_empty_branch_behind_main_is_fast_forwarded_on_the_remote(db, monkeypatch, tmp_path):
    seed, work, key, item, old = await _first_run_left(db, monkeypatch, tmp_path, own_commit=False)
    main = _advance_main(seed, work)
    tools = Tools(monkeypatch, {"create_github_branch": [EXISTS],
                                "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    _pushing(tools, monkeypatch)
    second = await _start(db, key, item)
    assert second.status == "waiting", second.context.get("actions")
    pushes = [args for tool, args in tools.calls if args.get("push_only")]
    assert [(args["branch_name"], args["local_path"]) for args in pushes] == [(_name(item), str(work))]
    assert tools.calls[-1][0] == "commit_and_push_github_repository_branch"
    assert _git(seed, "ls-remote", "origin", f"refs/heads/{_name(item)}").split()[0] == main
    assert second.context["branch_fast_forwarded"] == {"branch": _name(item), "old": old, "new": main,
                                                       "base_branch": "main"}
    assert second.context["branch_adoption"]["head"] == main and second.context["base_sha"] == main
    assert _git(work, "rev-parse", "HEAD") == main
    view = await run_view(db, second, access="write", user=await admin_user(db))
    assert view["adopted"]["branch"]["fast_forwarded_from"] == old


@pytest.mark.asyncio
async def test_an_adopted_branch_with_own_commits_is_never_moved_and_reports_behind(db, monkeypatch, tmp_path):
    seed, work, key, item, own = await _first_run_left(db, monkeypatch, tmp_path, own_commit=True)
    _advance_main(seed, work)
    tools = Tools(monkeypatch, {"create_github_branch": [EXISTS],
                                "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    _pushing(tools, monkeypatch)
    second = await _start(db, key, item)
    assert second.status == "waiting" and second.context["branch_adoption"]["commits"] == [own]
    assert not [args for _tool, args in tools.calls if args.get("push_only")]
    assert _git(seed, "ls-remote", "origin", f"refs/heads/{_name(item)}").split()[0] == own
    assert "branch_fast_forwarded" not in second.context
    adoption = (await run_view(db, second, access="write", user=await admin_user(db)))["adopted"]["branch"]
    assert (adoption["behind_base"], adoption["base_branch"]) == (1, "main")


@pytest.mark.asyncio
async def test_b_fast_forwards_its_adopted_branch_through_the_github_tool_before_preparing(
        client, auth_headers, db, systems):  # noqa: F811
    _project, item = await _workspace(db, systems)
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": B_KEY, "work_item_id": item.id})
    first_id = started.json()["run"]["id"]
    assert (await _settle(client, auth_headers, first_id))["current_node"]["id"] == "clarify"
    first = await db.get(WorkflowRun, first_id)
    branch = first.branch
    bare = systems["bare"]
    old = _git(bare, "rev-parse", f"refs/heads/{branch}")
    aborted = await client.post(f"/api/v1/workflow-runs/{first_id}/actions", headers=auth_headers,
                                json={"action": "abort", "reason": "restart after main moved"})
    assert aborted.status_code == 200, aborted.text
    clone = bare.parent / "merger"
    _git(bare.parent, "clone", "-q", str(bare), str(clone))
    main = _advance_main(clone, clone)
    assert main != old

    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": B_KEY, "work_item_id": item.id})
    assert started.status_code == 200, started.text
    second_id = started.json()["run"]["id"]
    view = await _settle(client, auth_headers, second_id)
    assert view["current_node"]["id"] == "clarify", view
    second = await db.get(WorkflowRun, second_id)
    await db.refresh(second)
    assert _git(bare, "rev-parse", f"refs/heads/{branch}") == main
    assert second.context["branch_fast_forwarded"] == {"branch": branch, "old": old, "new": main,
                                                       "base_branch": second.context["branch_fast_forwarded"]
                                                       ["base_branch"]}
    assert second.context["workspace_preparation"]["spec"]["head"] == main
    events = (await client.get(f"/api/v1/workflow-runs/{second_id}/events", headers=auth_headers)).json()["events"]
    assert [event["detail"]["new"] for event in events if event["kind"] == "branch_fast_forwarded"] == [main]


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
