"""The read-only gate of the Bitbucket write paths (``tools/bitbucket_impl/_bitbucket_write_gate.py``).

A repository the Workspace registered as a Knowledge repository source through a Bitbucket connection with
``access_mode: read_only`` is never written by the agent: every REST write tool (branch, pull request created or
updated, comment) and ``commit_and_push_repository_branch`` answer ``repository_read_only`` before any request or
``git commit``/``git push``; the REST transport refuses such a write from any other caller too. ``read_write``
writes; a repository the Workspace did not register behaves as today.
"""

from __future__ import annotations

import httpx
import pytest

from app.tools.bitbucket_impl import _bitbucket_cloud
from app.tools.bitbucket_impl import _bitbucket_internal_network as network
from app.tools.bitbucket_impl._bitbucket_branches import CreateBitbucketBranch
from app.tools.bitbucket_impl._bitbucket_delivery import AddBitbucketPullRequestComment
from app.tools.bitbucket_impl._bitbucket_pull_requests import CreateBitbucketPullRequest, UpdateBitbucketPullRequest
from app.tools.bitbucket_impl._bitbucket_write_gate import RepositoryWriteRefusedError, bitbucket_write_refusal
from app.tools.context import ToolContext
from tests.bitbucket_repository_access_gate_support import BASE, _context, _register, _workspace
from tests.knowledge_evidence_seed_support import seed_workspace

API = "/bitbucket/rest/api/1.0/projects/PROJ/repos/app"


class FakeDataCenter:
    """The Data Center REST API of ``PROJ/app``: every request is recorded."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def writes(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method != "GET"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        ref = {"id": "refs/heads/feature/x", "displayId": "feature/x"}
        pr = {"id": 5, "version": 1, "title": "t", "state": "OPEN", "fromRef": ref,
              "toRef": {"id": "refs/heads/main", "displayId": "main"}, "reviewers": []}
        if path == f"{API}/branches/default":
            return httpx.Response(200, json={"displayId": "main"})
        if path == f"{API}/branches" and method == "POST":
            return httpx.Response(200, json={"displayId": "feature/x", "latestCommit": "abc"})
        if path == f"{API}/pull-requests" and method == "GET":
            return httpx.Response(200, json={"values": []})
        if path == f"{API}/pull-requests" and method == "POST":
            return httpx.Response(201, json=pr)
        if path == f"{API}/pull-requests/5":
            return httpx.Response(200, json=pr)
        if path == f"{API}/pull-requests/5/comments" and method == "POST":
            return httpx.Response(201, json={"id": 9})
        return httpx.Response(404, json={})


@pytest.fixture
def datacenter(monkeypatch) -> FakeDataCenter:
    fake = FakeDataCenter()
    monkeypatch.setattr(network, "egress_transport", lambda *_a, **_k: httpx.MockTransport(fake.handle))
    return fake


async def _write_through_every_rest_tool(context: ToolContext) -> list[dict]:
    repo = {"project_key": "PROJ", "repo_slug": "app"}
    return [
        await CreateBitbucketBranch().execute({**repo, "branch_name": "feature/x"}, context),
        await CreateBitbucketPullRequest().execute(
            {**repo, "title": "t", "from_branch": "feature/x", "reviewers": ["lead"]}, context),
        await UpdateBitbucketPullRequest().execute({**repo, "pr_id": "5", "title": "t2"}, context),
        await AddBitbucketPullRequestComment().execute({**repo, "pr_id": "5", "text": "hello"}, context),
    ]


# --- REST write tools -------------------------------------------------------------------------------------------


async def test_rest_writes_into_a_read_only_repository_are_refused_before_any_request(db, datacenter):
    workspace_id = await _workspace(db)
    await _register(db, workspace_id, "read_only")

    results = await _write_through_every_rest_tool(_context(db, workspace_id))

    for result in results:
        assert result["code"] == "repository_read_only", result
        assert (result["project_key"], result["repo_slug"], result["connector"]) == ("PROJ", "app", "bitbucket")
        assert "read-only" in result["error"]
    assert datacenter.requests == [], "nothing reaches Bitbucket, not even a read"


async def test_rest_writes_into_a_read_write_repository_proceed(db, datacenter):
    workspace_id = await _workspace(db)
    await _register(db, workspace_id, "read_only")  # a second registration of the same repository: read_write wins
    await _register(db, workspace_id, "read_write")

    branch, created, updated, comment = await _write_through_every_rest_tool(_context(db, workspace_id))

    assert (branch["status"], created["status"], updated["status"], comment["status"]) == (
        "created", "created", "updated", "created")
    assert [(request.method, request.url.path.removeprefix(API)) for request in datacenter.writes()] == [
        ("POST", "/branches"), ("POST", "/pull-requests"), ("PUT", "/pull-requests/5"),
        ("POST", "/pull-requests/5/comments")]


async def test_an_unregistered_repository_is_written_as_today(db, datacenter):
    workspace_id = await _workspace(db)
    await _register(db, workspace_id, "read_only", remote=f"{BASE}/projects/PROJ/repos/other")
    elsewhere = await seed_workspace(db)
    await _register(db, elsewhere, "read_only")  # another Workspace's registration does not govern this one

    results = await _write_through_every_rest_tool(_context(db, workspace_id))

    assert [result.get("code") for result in results] == [None] * 4
    assert len(datacenter.writes()) == 4


async def test_the_session_workspace_decides_and_without_one_every_workspace_of_the_context(db, datacenter):
    workspace_id = await _workspace(db)
    other = await _workspace(db)
    await _register(db, other, "read_only")
    repo = {"project_key": "PROJ", "repo_slug": "app"}

    in_session = _context(db, workspace_id)
    in_session.project_ids = [other, workspace_id]
    in_session.project_config = {**in_session.project_config, "project_id": workspace_id}
    assert await bitbucket_write_refusal(in_session, **repo) is None

    without_session = _context(db, workspace_id)
    without_session.project_ids = [workspace_id, other]
    assert (await bitbucket_write_refusal(without_session, **repo))["code"] == "repository_read_only"

    assert await bitbucket_write_refusal(_context(None, other), **repo) is None, "no database: nothing registered"


async def test_the_rest_transport_refuses_a_write_from_any_caller_and_reads_pass(db, datacenter):
    workspace_id = await _workspace(db)
    await _register(db, workspace_id, "read_only")
    context = _context(db, workspace_id)

    with pytest.raises(RepositoryWriteRefusedError) as refused:
        await network._bitbucket_json_post(
            context, "/rest/branch-utils/1.0/projects/proj/repos/app/branches", payload={"name": "x"})
    with pytest.raises(RepositoryWriteRefusedError):
        await network._bitbucket_json_put(context, "/rest/api/1.0/projects/PROJ/repos/APP/pull-requests/5",
                                          payload={})
    assert datacenter.requests == []
    assert refused.value.refusal["code"] == "repository_read_only"

    assert await network._bitbucket_json_get(context, "/rest/api/1.0/projects/PROJ/repos/app/branches/default") == {
        "displayId": "main"}


async def test_bitbucket_cloud_writes_are_gated_by_workspace_and_slug(db, monkeypatch):
    calls: list[tuple[str, str]] = []

    def cloud(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/2.0/repositories/acme/payments/refs/branches/main":
            return httpx.Response(200, json={"name": "main", "target": {"hash": "a" * 40}})
        if request.url.path == "/2.0/repositories/acme/payments":
            return httpx.Response(200, json={"mainbranch": {"name": "main"}})
        return httpx.Response(201, json={"name": "feature/x", "target": {"hash": "a" * 40}})

    monkeypatch.setattr(_bitbucket_cloud, "_transport", lambda: httpx.MockTransport(cloud))
    workspace_id = await _workspace(db, name="acme/payments")
    await _register(db, workspace_id, "read_only", remote="https://bitbucket.org/acme/payments", cloud=True)
    context = _context(db, workspace_id)
    context.project_config = {"bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org",
                              "bitbucket_username": "dev@example.test", "bitbucket_token": "tok",
                              "bitbucket_allowed_repos": [{"project_key": "ACME", "repo_slug": "payments"}]}

    branch = await CreateBitbucketBranch().execute(
        {"project_key": "ACME", "repo_slug": "payments", "branch_name": "feature/x"}, context)
    assert (branch["code"], branch["project_key"], branch["repo_slug"]) == ("repository_read_only", "acme", "payments")
    with pytest.raises(RepositoryWriteRefusedError):
        await _bitbucket_cloud.cloud_request(context, "PUT", "/repositories/acme/payments/pullrequests/1", payload={})
    assert calls == []

    await _register(db, workspace_id, "read_write", remote="https://bitbucket.org/acme/payments", cloud=True)
    branch = await CreateBitbucketBranch().execute(
        {"project_key": "ACME", "repo_slug": "payments", "branch_name": "feature/x"}, context)
    assert branch["status"] == "created"
    assert ("POST", "/2.0/repositories/acme/payments/refs/branches") in calls
