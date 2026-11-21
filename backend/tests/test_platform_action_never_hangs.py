"""A platform action never leaves its run silently ``running``.

A platform action records a result or offers a retry. The test covers:

- the branch create is idempotent: an existing empty branch is adopted through the real Bitbucket Cloud tools, and
  the provider's refusal body is in the log;
- an exception inside a platform action is the step's recorded failure: the run pauses with "Retry the step";
- a run whose action request died (``running`` at a platform action without a result) offers "Retry the step".
"""

from __future__ import annotations

import logging
from datetime import timedelta

import httpx
import pytest

from app.models import CodeRepository
from app.models.runtime.secure_work import WorkItem
from app.services.workflow_runs.actions import available_actions, perform_action
from app.services.workflow_runs.platform import dispatch as dispatch_module
from app.services.workflow_runs.platform import scm
from app.services.workflow_runs.platform.dispatch import read_outcome
from app.time_utils import utc_now
from tests.bitbucket_cloud_workflow_support import _cloud_workspace
from tests.phased_workflow_fixtures import admin_user
from tests.test_workflow_run_platform_actions import _run as start
from tests.workflow_run_succession_support import BRANCH, Tools, _git, _origin, _remote_branch

MAIN = "a" * 40


class Cloud:
    """Bitbucket Cloud as a run sees it: the repository and main answer, the branch create says it exists."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if request.method == "GET" and path == "/2.0/repositories/acme/payments":
            return httpx.Response(200, json={"mainbranch": {"name": "main"}})
        if request.method == "GET" and path == "/2.0/repositories/acme/payments/refs/branches/main":
            return httpx.Response(200, json={"name": "main", "target": {"hash": MAIN}})
        if request.method == "POST" and path == "/2.0/repositories/acme/payments/refs/branches":
            return httpx.Response(400, json={"type": "error", "error": {
                "message": "BRANCH_ALREADY_EXISTS", "data": {"key": "BRANCH_ALREADY_EXISTS"}}})
        return httpx.Response(404, json={"type": "error", "error": {"message": "Not found"}})


async def _cloud_item(db) -> tuple[str, WorkItem]:
    workspace_id = await _cloud_workspace(db)
    db.add(CodeRepository(project_id=workspace_id, provider="bitbucket", name="acme/payments", is_active=True,
                          repo_root="/srv/repos/payments", remote_url="https://bitbucket.org/acme/payments.git",
                          config_json={"operation_policy": {"read": True, "branch": True, "write": True,
                                                            "pr": True}}))
    item = WorkItem(source_type="jira", source_instance="test", source_key="CHEF-14", source_project_key="CHEF",
                    title="Hello kitchen", work_state="development", project_id=workspace_id)
    db.add(item)
    await db.flush()
    return workspace_id, item


@pytest.mark.asyncio
async def test_an_existing_empty_branch_on_bitbucket_cloud_is_adopted_and_the_refusal_is_logged(
        db, monkeypatch, tmp_path, caplog):
    from app.tools.bitbucket_impl import _bitbucket_cloud

    cloud = Cloud()
    monkeypatch.setattr(_bitbucket_cloud, "_transport", lambda: httpx.MockTransport(cloud.handler))
    seed, work = _origin(tmp_path)
    real_dispatch = dispatch_module.dispatch_tool

    async def dispatch(db, run, tool, arguments, **kwargs):
        if tool == "prepare_bitbucket_repository":  # the clone: a local origin that has the branch at main
            return read_outcome({"local_path": str(work), "base_branch": "main"})
        return await real_dispatch(db, run, tool, arguments, **kwargs)

    monkeypatch.setattr(scm, "dispatch_tool", dispatch)
    workspace_id, item = await _cloud_item(db)
    _remote_branch(seed, work, "feature/CHEF-14-hello-kitchen")  # the crashed first run's branch, never recorded

    with caplog.at_level(logging.WARNING):
        run = await start(db, BRANCH, project_id=workspace_id, repository="bitbucket:acme/payments",
                          work_item_id=item.id)

    assert ("POST", "/2.0/repositories/acme/payments/refs/branches") in cloud.calls
    assert (run.status, run.branch) == ("waiting", "feature/CHEF-14-hello-kitchen"), run.context.get("actions")
    assert run.context["branch_adoption"]["commits"] == [] and run.context["branch_adoption"]["from_runs"] == []
    assert run.context["base_sha"] == _git(work, "rev-parse", "origin/main")
    refused = [record for record in caplog.records if record.getMessage() == "connector.http_refused"]
    assert refused and refused[0].status_code == 400 and "BRANCH_ALREADY_EXISTS" in refused[0].body
    assert refused[0].path == "/2.0/repositories/acme/payments/refs/branches"


@pytest.mark.asyncio
async def test_an_exception_inside_the_action_pauses_the_run_with_retry_the_step(db, monkeypatch, tmp_path):
    _seed, work = _origin(tmp_path)
    tools = Tools(monkeypatch, {"create_github_branch": [{"status": "created"}],
                                "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    real_create = scm.create_branch
    raised = []

    async def crashing(db, run, params):
        if not raised:
            raised.append(True)
            raise RuntimeError("Can't operate on closed transaction inside context manager")
        return await real_create(db, run, params)

    from app.services.workflow_runs.platform import catalog

    monkeypatch.setattr(scm, "create_branch", crashing)
    item = WorkItem(source_type="jira", source_instance="test", source_key="BRD-9", source_project_key="BRD",
                    title="Add a slugify function", work_state="development")
    db.add(item)
    await db.flush()
    run = await start(db, BRANCH, repository="github:acme/payments", work_item_id=item.id)

    assert (run.status, run.pause_reason) == ("paused", "action_failed")
    failure = run.node_state["pause"]["failure"]
    assert failure["action"] == catalog.SCM_CREATE_BRANCH and failure["recoverable"] is True
    assert failure["reason"] == "RuntimeError: Can't operate on closed transaction inside context manager"
    admin = await admin_user(db)
    offered = [action["key"] for action in await available_actions(db, run, access="write", user=admin)]
    assert offered[0] == "retry_action"
    await perform_action(db, run, user=admin, body={"action": "retry_action"})
    assert (run.status, run.branch) == ("waiting", "feature/BRD-9-add-a-slugify-function")
    assert tools.tools().count("create_github_branch") == 1


@pytest.mark.asyncio
async def test_a_run_whose_action_request_died_offers_retry_the_step(db, monkeypatch, tmp_path):
    _seed, work = _origin(tmp_path)
    tools = Tools(monkeypatch, {"create_github_branch": [{"status": "created"}],
                                "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    item = WorkItem(source_type="jira", source_instance="test", source_key="BRD-10", source_project_key="BRD",
                    title="Add a slugify function", work_state="development")
    db.add(item)
    await db.flush()
    run = await start(db, BRANCH, repository="github:acme/payments", work_item_id=item.id)
    # What the crashed request left (committed mid-action): running at ``branch``, its pass without a result.
    entry = 2
    run.status, run.current_node_id, run.branch, run.waiting_kind = "running", "branch", None, None
    run.context = {key: value for key, value in run.context.items() if key not in ("action_ledger", "local_path", "branch_created")}
    entered = utc_now().replace(tzinfo=None)
    run.node_state = {"node_id": "branch", "iteration": 1, "entry": entry, "entered_at": entered.isoformat()}
    admin = await admin_user(db)

    keys = lambda offered: [action["key"] for action in offered]  # noqa: E731
    assert "retry_step" not in keys(await available_actions(db, run, access="write", user=admin)), "still working"
    run.node_state = {**run.node_state, "entered_at": (entered - timedelta(minutes=6)).isoformat()}
    offered = await available_actions(db, run, access="write", user=admin)
    assert keys(offered)[0] == "retry_step" and offered[0]["label"] == "Retry the step"

    await perform_action(db, run, user=admin, body={"action": "retry_step"})
    assert (run.status, run.branch) == ("waiting", "feature/BRD-10-add-a-slugify-function")
    assert tools.tools().count("create_github_branch") == 2  # the step really ran again (a new pass)
    assert "retry_step" not in keys(await available_actions(db, run, access="write", user=admin))
