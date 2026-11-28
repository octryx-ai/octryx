"""Bitbucket Cloud as a Bitbucket connection (``bitbucket_deployment: cloud``), against a stub of the REST 2.0 API."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.models import CodeRepository
from app.services.connector_test.collab import test_bitbucket_connection as run_bitbucket_connection_test
from app.services.named_connections.descriptor import UnitIncompleteError
from app.services.named_connections.descriptors import descriptor_of
from app.tools.bitbucket_impl import _bitbucket_cloud
from app.tools.bitbucket_impl._bitbucket_branches import CreateBitbucketBranch
from app.tools.bitbucket_impl._bitbucket_delivery import AddBitbucketPullRequestComment, GetBitbucketBuildStatuses
from app.tools.bitbucket_impl._bitbucket_internal_core import _bitbucket_clone_url, _bitbucket_git_auth_env_async
from app.tools.bitbucket_impl._bitbucket_internal_network import _bitbucket_json_get
from app.tools.bitbucket_impl._bitbucket_pull_requests import CreateBitbucketPullRequest, GetBitbucketPullRequest
from app.tools.context import ToolContext
from tests.agent_definition_revision_fixtures import make_project

EMAIL, TOKEN = "dev@example.test", "fake-cloud-token"
OWN, LEAD, GHOST = "557058:00000000-0000-0000-0000-00000000000a", "557058:00000000-0000-0000-0000-00000000000b", (
    "557058:00000000-0000-0000-0000-00000000000c")
HEAD = "a" * 40
REPO = "/2.0/repositories/acme/payments"


class FakeBitbucketCloud:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.prs: list[dict] = []

    def _pr(self, number: int, branch: str, reviewers: list[str], state: str = "OPEN") -> dict:
        return {"id": number, "title": "t", "state": state, "source": {"branch": {"name": branch},
                                                                     "commit": {"hash": HEAD[:12]}},
                "destination": {"branch": {"name": "main"}}, "author": {"display_name": "Dev"},
                "links": {"html": {"href": f"https://bitbucket.org/acme/payments/pull-requests/{number}"}},
                "participants": [{"role": "REVIEWER", "approved": state == "MERGED",
                                  "user": {"display_name": "Lead", "account_id": item}} for item in reviewers]}

    def handler(self, request: httpx.Request) -> httpx.Response:
        expected = "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
        assert request.headers["authorization"] == expected and request.url.host == "api.bitbucket.org"
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))
        if path == "/2.0/user":
            return httpx.Response(200, json={"account_id": OWN, "display_name": "Dev"})
        if path.startswith("/2.0/users/"):
            return httpx.Response(200, json={"account_id": LEAD}) if path.endswith(LEAD) else httpx.Response(
                404, json={"type": "error", "error": {"message": "User not found"}})
        if path == REPO:
            return httpx.Response(200, json={"full_name": "acme/payments", "mainbranch": {"name": "main"}})
        if path == f"{REPO}/refs/branches/main":
            return httpx.Response(200, json={"name": "main", "target": {"hash": HEAD}})
        if path == f"{REPO}/refs/branches" and request.method == "POST":
            return httpx.Response(201, json={"name": body["name"], "target": {"hash": body["target"]["hash"]}})
        if path == f"{REPO}/pullrequests" and request.method == "GET":
            return httpx.Response(200, json={"values": [pr for pr in self.prs if pr["state"] == "OPEN"]})
        if path == f"{REPO}/pullrequests" and request.method == "POST":
            pr = self._pr(len(self.prs) + 1, body["source"]["branch"]["name"],
                          [item["account_id"] for item in body["reviewers"]])
            self.prs.append(pr)
            return httpx.Response(201, json=pr)
        if path == f"{REPO}/pullrequests/1":
            return httpx.Response(200, json=self._pr(1, "feature/PAY-1", [LEAD], state="MERGED"))
        if path == f"{REPO}/pullrequests/1/comments":
            return httpx.Response(201, json={"id": 77, "links": {"html": {"href": "https://bitbucket.org/c/77"}}})
        if path == f"{REPO}/commit/{HEAD}/statuses":
            return httpx.Response(200, json={"values": [
                {"state": "SUCCESSFUL", "key": "pipeline", "name": "Pipeline #4", "url": "https://bitbucket.org/p/4"}]})
        return httpx.Response(404, json={"type": "error", "error": {"message": "Not found"}})


@pytest.fixture
def cloud(monkeypatch) -> FakeBitbucketCloud:
    fake = FakeBitbucketCloud()
    monkeypatch.setattr(_bitbucket_cloud, "_transport", lambda: httpx.MockTransport(fake.handler))
    return fake


async def _context(db) -> ToolContext:
    project = await make_project(db)
    db.add(CodeRepository(project_id=project.id, provider="bitbucket", name="acme/payments", is_active=True,
                          repo_root="/srv/repos", config_json={"operation_policy": {"branch": True, "pr": True}}))
    await db.flush()
    config = {"bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org",
              "bitbucket_username": EMAIL, "bitbucket_token": TOKEN,
              "bitbucket_allowed_repos": [{"project_key": "ACME", "repo_slug": "payments", "enabled": True}]}
    return ToolContext(user_id="u", project_ids=[project.id], roles=[], session_id=None, project_config=config, db=db)


def test_a_cloud_connection_is_bitbucket_org_with_the_account_email_and_an_api_token():
    complete = descriptor_of("bitbucket").complete
    complete({"bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org", "bitbucket_username": EMAIL,
              "bitbucket_token_secret_ref": "s1"})
    for broken in ({"bitbucket_url": "https://bitbucket.example.test"}, {"bitbucket_username": ""},
                   {"bitbucket_token_secret_ref": "", "bitbucket_password": "pw"}, {"bitbucket_deployment": "other"}):
        with pytest.raises(UnitIncompleteError):
            complete({"bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org",
                      "bitbucket_username": EMAIL, "bitbucket_token_secret_ref": "s1", **broken})
    complete({"bitbucket_url": "https://bitbucket.example.test", "bitbucket_auth_mode": "bearer_pat",
              "bitbucket_token": "t"})
    with pytest.raises(UnitIncompleteError, match="bitbucket_auth_mode"):
        complete({"bitbucket_url": "https://bitbucket.example.test", "bitbucket_token": "t"})


async def test_git_uses_the_cloud_clone_url_and_the_api_token_user_and_server_paths_are_refused(db):
    context = await _context(db)
    url = _bitbucket_clone_url(context, "ACME", "payments")
    assert url == "https://bitbucket.org/acme/payments.git"
    env = await _bitbucket_git_auth_env_async(context, url)
    assert (env["OCTRYX_BITBUCKET_USERNAME"], env["OCTRYX_BITBUCKET_SECRET"]) == (
        "x-bitbucket-api-token-auth", TOKEN)
    with pytest.raises(ValueError, match="Bitbucket Cloud"):
        await _bitbucket_json_get(context, "/rest/api/1.0/projects/ACME/repos/payments/commits")


async def test_branch_pull_request_state_comment_and_build_statuses_on_cloud(db, cloud):
    context = await _context(db)
    branch = await CreateBitbucketBranch().execute(
        {"project_key": "ACME", "repo_slug": "payments", "branch_name": "feature/PAY-1"}, context)
    assert branch["status"] == "created" and branch["latest_commit"] == HEAD
    assert ("POST", f"{REPO}/refs/branches", {"name": "feature/PAY-1", "target": {"hash": HEAD}}) in cloud.calls

    args = {"project_key": "ACME", "repo_slug": "payments", "title": "PAY-1: totals", "from_branch": "feature/PAY-1"}
    created = await CreateBitbucketPullRequest().execute({**args, "reviewers": [LEAD, GHOST]}, context)
    assert created["status"] == "created" and created["reviewers_unresolved"] == [GHOST]
    assert created["url"] == "https://bitbucket.org/acme/payments/pull-requests/1"
    sent = next(body for method, path, body in cloud.calls if method == "POST" and path == f"{REPO}/pullrequests")
    assert sent["reviewers"] == [{"account_id": LEAD}] and sent["destination"] == {"branch": {"name": "main"}}
    again = await CreateBitbucketPullRequest().execute({**args, "reviewers": [LEAD]}, context)
    assert again["status"] == "existing" and len(cloud.prs) == 1
    cloud.prs.clear()
    author = await CreateBitbucketPullRequest().execute({**args, "reviewers": [OWN, LEAD], "requester": OWN},
                                                        context)
    assert author["reviewer_skipped"] == "requester_is_author" and len(cloud.prs) == 1
    sent = [body for method, path, body in cloud.calls if method == "POST" and path == f"{REPO}/pullrequests"][-1]
    assert sent["reviewers"] == [{"account_id": LEAD}] and f"Requested by @{{{OWN}}}" in sent["description"]

    state = await GetBitbucketPullRequest().execute({"project_key": "ACME", "repo_slug": "payments", "pr_id": 1},
                                                   context)
    assert state["state"] == "MERGED" and state["reviewers"][0]["approved"] is True

    cloud.prs.append(cloud._pr(1, "feature/PAY-1", [LEAD]))
    comment = await AddBitbucketPullRequestComment().execute(
        {"project_key": "ACME", "repo_slug": "payments", "from_branch": "feature/PAY-1", "text": "Verdict: pass"},
        context)
    assert (comment["status"], comment["pr_id"], comment["comment_id"]) == ("created", "1", 77)
    assert ("POST", f"{REPO}/pullrequests/1/comments", {"content": {"raw": "Verdict: pass"}}) in cloud.calls

    statuses = await GetBitbucketBuildStatuses().execute(
        {"project_key": "ACME", "repo_slug": "payments", "branch": "main"}, context)
    assert statuses["commit"] == HEAD and [item["state"] for item in statuses["statuses"]] == ["SUCCESSFUL"]
    assert TOKEN not in json.dumps([branch, created, author, state, comment, statuses])


async def test_the_cloud_connection_test_reads_the_account_and_names_missing_scopes(monkeypatch):
    answers = iter([httpx.Response(200, json={"account_id": OWN}), httpx.Response(401)])
    seen: list[str] = []

    class Module:
        class AsyncClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                def handler(request: httpx.Request) -> httpx.Response:
                    seen.append(str(request.url))
                    return next(answers)

                super().__init__(transport=httpx.MockTransport(handler))

    config = {"bitbucket_deployment": "cloud", "bitbucket_username": EMAIL, "bitbucket_token": TOKEN}
    assert (await run_bitbucket_connection_test(config, httpx_module=Module))["ok"] is True
    refused = await run_bitbucket_connection_test(config, httpx_module=Module)
    assert refused["ok"] is False and "Bitbucket scopes" in refused["summary"]
    assert seen == ["https://api.bitbucket.org/2.0/user"] * 2
