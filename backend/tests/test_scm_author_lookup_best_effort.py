"""The PR author lookup is best-effort on every SCM.

Asking the SCM who the connection's account is (``GET /user``) before opening the pull request never fails the step:
a token that may not read its own account (GitHub App / fine-grained token, a Bitbucket Cloud token without
``read:user:bitbucket``, an SCM without that endpoint) leaves the author unknown; the requester is then requested as
reviewer (the default); if the SCM refuses that reviewer, the pull request is still opened without them and the answer says
``reviewer_skipped: reviewer_refused``, which the run card and Inbox turn into "review and merge it yourself".
"""

from __future__ import annotations

import json

import httpx
import pytest

import app.tools.connectors.github_pull_requests as github_prs
import app.tools.connectors.gitlab_merge_requests as gitlab_mrs
from app.models import WorkflowRun
from app.services.workflow_runs.run_notices import reviewer_notice
from app.tools.bitbucket_impl import _bitbucket_cloud
from app.tools.bitbucket_impl._bitbucket_pull_requests import CreateBitbucketPullRequest
from app.tools.context import ToolContext
from app.tools.scm_requester_rule import REVIEWER_REFUSED
from tests.test_bitbucket_cloud_tools import LEAD, OWN, REPO, TOKEN, FakeBitbucketCloud, _context

ARGS = {"title": "PAY-1: totals", "from_branch": "feature/PAY-1"}


def _status_error(url: str, status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    return httpx.HTTPStatusError("refused", request=request, response=httpx.Response(status, request=request))


class CloudWithoutAccountRead(FakeBitbucketCloud):
    """A token without ``read:user``: ``/2.0/user`` is refused; Bitbucket refuses the author as a reviewer."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2.0/user":
            self.calls.append((request.method, request.url.path, None))
            return httpx.Response(403, json={"type": "error", "error": {"message": "Token lacks read:user"}})
        if request.url.path == f"/2.0/users/{OWN}":
            return httpx.Response(200, json={"account_id": OWN})  # the account exists; only reading "me" is refused
        reviewers = json.loads(request.content).get("reviewers", []) if request.method == "POST" else []
        if request.url.path == f"{REPO}/pullrequests" and {"account_id": OWN} in reviewers:
            self.calls.append((request.method, request.url.path, None))
            return httpx.Response(400, json={"type": "error", "error": {"message": "author cannot be a reviewer"}})
        return super().handler(request)


@pytest.fixture
def cloud(monkeypatch) -> CloudWithoutAccountRead:
    fake = CloudWithoutAccountRead()
    monkeypatch.setattr(_bitbucket_cloud, "_transport", lambda: httpx.MockTransport(fake.handler))
    return fake


@pytest.mark.asyncio
async def test_bitbucket_cloud_opens_the_pull_request_without_reading_its_own_account(db, cloud):
    context = await _context(db)
    args = {**ARGS, "project_key": "ACME", "repo_slug": "payments"}
    # The requester is not the author: requested as reviewer at the first try.
    other = await CreateBitbucketPullRequest().execute({**args, "reviewers": [LEAD], "requester": LEAD}, context)
    assert other["status"] == "created" and "reviewer_skipped" not in other
    cloud.prs.clear()
    # The requester is the (unknown) author: Bitbucket refuses them, the PR opens without them and mentions them.
    own = await CreateBitbucketPullRequest().execute({**args, "reviewers": [OWN, LEAD], "requester": OWN}, context)
    assert (own["status"], own["reviewer_skipped"]) == ("created", REVIEWER_REFUSED) and len(cloud.prs) == 1
    sent = [body for method, path, body in cloud.calls if method == "POST" and path == f"{REPO}/pullrequests" and body]
    assert sent[-1]["reviewers"] == [{"account_id": LEAD}] and f"@{{{OWN}}}" in sent[-1]["description"]
    assert TOKEN not in str(own)


@pytest.mark.asyncio
async def test_bitbucket_cloud_still_fails_a_refusal_it_cannot_explain(db, monkeypatch):
    """With the author known, a 400 is not the author case: no silent retry, the step fails with Bitbucket's text."""

    class Refusing(FakeBitbucketCloud):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{REPO}/pullrequests" and request.method == "POST":
                self.calls.append((request.method, request.url.path, None))
                return httpx.Response(400, json={"type": "error", "error": {"message": "branch not found"}})
            return super().handler(request)

    fake = Refusing()
    monkeypatch.setattr(_bitbucket_cloud, "_transport", lambda: httpx.MockTransport(fake.handler))
    answer = await CreateBitbucketPullRequest().execute(
        {**ARGS, "project_key": "ACME", "repo_slug": "payments", "reviewers": [LEAD], "requester": LEAD},
        await _context(db))
    assert answer.get("status") != "created" and "branch not found" in str(answer)
    assert len([call for call in fake.calls if call[0] == "POST" and call[1] == f"{REPO}/pullrequests"]) == 1


def _scm_context() -> ToolContext:
    return ToolContext(user_id="u", project_ids=["p"], roles=[], session_id="s",
                       project_config={"github_url": "https://scm.test/api/v3", "gitlab_url": "https://gl.test"})


async def _none(*_args, **_kwargs):
    return None


async def _headers(_context):
    return {}


@pytest.mark.asyncio
@pytest.mark.parametrize("refuse_reviewer", [False, True])
async def test_github_opens_the_pull_request_when_user_is_unreadable(monkeypatch, refuse_reviewer):
    sent: list[str] = []

    async def http(method, url, **kwargs):
        sent.append(url)
        if url.endswith("/user"):
            raise _status_error(url, 404)  # GitHub App tokens / the stub: no /user
        if url.endswith("/requested_reviewers"):
            if refuse_reviewer:
                raise _status_error(url, 422)  # "Review cannot be requested from pull request author."
            return {"requested_reviewers": [{"login": name} for name in kwargs["json_body"]["reviewers"]]}
        return {"number": 9, "html_url": "https://scm.test/pr/9"}

    monkeypatch.setattr(github_prs, "_http_json", http)
    monkeypatch.setattr(github_prs, "require_github_repository_operation", _none)
    monkeypatch.setattr(github_prs, "_github_headers", _headers)
    answer = await github_prs.CreateGitHubPullRequestTool().execute(
        {**ARGS, "repository": "acme/payments", "to_branch": "main", "reviewers": ["dev", "lead"],
         "requester": "dev"}, _scm_context())
    assert answer["status"] == "created" and answer["number"] == 9
    if refuse_reviewer:
        assert answer["reviewer_skipped"] == REVIEWER_REFUSED and answer["reviewers_unresolved"] == ["dev", "lead"]
    else:
        assert "reviewer_skipped" not in answer and answer["reviewers"] == ["dev", "lead"]


@pytest.mark.asyncio
async def test_gitlab_opens_the_merge_request_when_user_is_unreadable(monkeypatch):
    async def http(method, url, **kwargs):
        if url.endswith("/user"):
            raise _status_error(url, 403)
        if url.endswith("/users"):
            return [{"id": 42}]
        return {"iid": 2, "web_url": "https://gl.test/mr/2", "reviewers": [{"username": "dev"}]}

    monkeypatch.setattr(gitlab_mrs, "_http_json", http)
    monkeypatch.setattr(gitlab_mrs, "require_gitlab_repository_operation", _none)
    monkeypatch.setattr(gitlab_mrs, "_gitlab_headers", _headers)
    answer = await gitlab_mrs.CreateGitLabMergeRequestTool().execute(
        {**ARGS, "project": "acme/payments", "to_branch": "main", "reviewers": ["dev"], "requester": "dev"},
        _scm_context())
    assert answer["status"] == "created" and "reviewer_skipped" not in answer


def test_the_run_card_tells_the_requester_to_review_a_refused_pull_request():
    run = WorkflowRun(pull_request={"provider": "bitbucket", "url": "https://bitbucket.org/a/b/pull-requests/1",
                                    "reviewer_skipped": REVIEWER_REFUSED})
    notice = reviewer_notice(run)
    assert notice["reason"] == REVIEWER_REFUSED and "did not accept you" in notice["text"]
