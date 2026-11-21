"""PR review bot, provider tools against recorded API answers (no network).

- GitHub: the summary comment carrying the marker is edited in place (one summary per pull request, on every push),
  the inline comments go out as one ``COMMENT`` review on the head commit (never an approval or a change request),
  a 422 for a comment off the diff keeps the summary and the status and names the refusal; the status is
  ``octryx/review``; the open heads are read page by page;
- Bitbucket Cloud: summary edited by marker, inline comments on ``inline.to``, build status with key
  ``octryx-review`` and the required ``url``; open heads page by page;
- Bitbucket Server/Data Center: summary found in the activities and edited with its version, inline comments
  anchored with ``lineType`` / ``fileType: TO``, ``/rest/build-status/1.0`` status.
"""

# ruff: noqa: F811  (the shared ``github_api`` and ``cloud_api`` fixtures are imported, then requested by name)
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.tools.bitbucket_impl import _bitbucket_internal_network
from app.tools.bitbucket_impl import _bitbucket_pr_review as bitbucket
from app.tools.connectors import github_pr_review as github
from tests.pr_review_bot_support import Recorder, cloud_api, github_api  # noqa: F401 - fixtures

FIXTURES = Path(__file__).parent / "fixtures" / "pr_review_bot"
SHA = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"
MARKER = "<!-- octryx-review-summary -->"
CONTEXT = SimpleNamespace(project_config={"github_allowed_repositories": ["acme/pay"]}, project_ids=["ws"], db=None,
                          user_id="bot")
COMMENTS = [{"path": "pay/totals.py", "line": 7, "start_line": 6, "body": "fix", "line_type": "ADDED"},
            {"path": "pay/new.py", "line": 1, "body": "name it", "line_type": "CONTEXT"}]
STATUS = {"state": "failure", "description": "1 blocking finding(s): 1 high", "context": "octryx/review",
          "target_url": "https://octryx.example.test/chat?session_id=s1"}


async def test_github_edits_its_summary_posts_one_comment_review_and_sets_the_status(github_api):
    github_api.answers = {
        ("GET", "/repos/acme/pay/issues/42/comments"): [{"id": 5, "body": "LGTM"}, {"id": 9, "body": f"{MARKER}\nold"}],
        ("PATCH", "/repos/acme/pay/issues/comments/9"): {"id": 9},
        ("POST", "/repos/acme/pay/pulls/42/reviews"): {"id": 77},
    }
    result = await github.PostGitHubPullRequestReviewTool().execute(
        {"repository": "acme/pay", "pr_number": "42", "commit": SHA, "summary": f"{MARKER}\nnew", "marker": MARKER,
         "comments": COMMENTS, "commit_status": STATUS}, CONTEXT)
    assert (result["summary"], result["summary_comment_id"], result["review_id"], result["inline_posted"]) == (
        "updated", 9, 77, 2)
    methods = [(method, path) for method, path, _body, _params in github_api.calls]
    assert ("POST", "/repos/acme/pay/issues/42/comments") not in methods  # edited, never a second summary
    review = next(body for method, path, body, _ in github_api.calls if path.endswith("/reviews"))
    assert (review["event"], review["commit_id"]) == ("COMMENT", SHA)
    assert review["comments"][0] == {"path": "pay/totals.py", "line": 7, "side": "RIGHT", "body": "fix",
                                     "start_line": 6, "start_side": "RIGHT"}
    status = next(body for method, path, body, _ in github_api.calls if path == f"/repos/acme/pay/statuses/{SHA}")
    assert status == {"state": "failure", "context": "octryx/review", "description": "1 blocking finding(s): 1 high",
                      "target_url": "https://octryx.example.test/chat?session_id=s1"}


async def test_github_keeps_summary_and_status_when_it_refuses_the_inline_comments(github_api):
    refused = httpx.HTTPStatusError("422", request=httpx.Request("POST", "https://x"),
                                    response=httpx.Response(422, text='{"message":"line must be part of the diff"}'))
    github_api.answers = {("GET", "/repos/acme/pay/issues/42/comments"): [],
                          ("POST", "/repos/acme/pay/issues/42/comments"): {"id": 3},
                          ("POST", "/repos/acme/pay/pulls/42/reviews"): refused}
    result = await github.PostGitHubPullRequestReviewTool().execute(
        {"repository": "acme/pay", "pr_number": "42", "commit": SHA, "summary": "s", "marker": MARKER,
         "comments": COMMENTS, "commit_status": STATUS}, CONTEXT)
    assert (result["summary"], result["inline_posted"], result["commit_status"]) == ("created", 0, "failure")
    assert "part of the diff" in result["inline_refused"]


async def test_github_reads_every_open_head_page_by_page(github_api):
    page = json.loads((FIXTURES / "github_pulls_page.json").read_text())
    github_api.answers = {("GET", "/repos/acme/pay/pulls"): lambda params: page * 34 if params["page"] == 1 else page}
    result = await github.ListGitHubPullRequestHeadsTool().execute({"repository": "acme/pay"}, CONTEXT)
    assert len(result["pull_requests"]) == 105  # 102 on a full first page, 3 on the second: none cut
    assert result["pull_requests"][0]["head_sha"] == SHA


async def test_bitbucket_cloud_edits_its_summary_comments_inline_and_sets_the_build_status(cloud_api):
    base = "/repositories/acme/payments/pullrequests/7/comments"
    cloud_api.answers = {("GET", base): {"values": [{"id": 4, "content": {"raw": f"{MARKER} old"}}]}}
    result = await bitbucket.PostBitbucketPullRequestReview().execute(
        {"project_key": "acme", "repo_slug": "payments", "pr_id": 7, "commit": SHA, "summary": f"{MARKER} new",
         "marker": MARKER, "comments": COMMENTS, "commit_status": STATUS}, CONTEXT)
    assert (result["summary"], result["inline_posted"], result["commit_status"]) == ("updated", 2, "FAILED")
    writes = [(method, path, body) for method, path, body, _ in cloud_api.calls if method != "GET"]
    assert writes[0] == ("PUT", f"{base}/4", {"content": {"raw": f"{MARKER} new"}})
    assert writes[1] == ("POST", base, {"content": {"raw": "fix"}, "inline": {"path": "pay/totals.py", "to": 7}})
    assert writes[3] == ("POST", f"/repositories/acme/payments/commit/{SHA}/statuses/build", {
        "key": "octryx-review", "name": "Octryx review", "state": "FAILED", "url": STATUS["target_url"],
        "description": STATUS["description"]})


async def test_bitbucket_cloud_reads_open_heads_until_no_next_page(cloud_api):
    page = json.loads((FIXTURES / "bitbucket_cloud_pullrequests_page.json").read_text())
    cloud_api.answers = {("GET", "/repositories/acme/payments/pullrequests"): lambda params: (
        {**page, "next": "https://api.bitbucket.org/…?page=2"} if params["page"] == 1 else page)}
    result = await bitbucket.ListBitbucketPullRequestHeads().execute(
        {"project_key": "acme", "repo_slug": "payments"}, CONTEXT)
    assert [(item["number"], item["head_sha"], item["head_repository"]) for item in result["pull_requests"]] == [
        (7, "c0ffee00c0ff", "acme/payments")] * 2


async def test_bitbucket_server_edits_by_version_anchors_inline_and_posts_build_status(monkeypatch):
    api = Recorder({})
    base = "/rest/api/1.0/projects/SHOP/repos/demo-shop/pull-requests/12"
    api.answers = {("GET", f"{base}/activities"): {"isLastPage": True, "values": [
        {"action": "COMMENTED", "comment": {"id": 31, "version": 2, "text": f"{MARKER} old"}}]},
        ("GET", "/rest/api/1.0/projects/SHOP/repos/demo-shop/pull-requests"): json.loads(
            (FIXTURES / "bitbucket_server_pull_requests_page.json").read_text())}

    async def get(_context, path, *, params=None):
        return api.answer("GET", path, None, params)

    async def post(_context, path, *, payload):
        return api.answer("POST", path, payload), 201

    async def put(_context, path, *, payload):
        return api.answer("PUT", path, payload), 200

    async def allowed(*_args, **_kwargs):
        return None

    for name, value in (("_bitbucket_json_post", post), ("_bitbucket_json_put", put),
                        ("require_project_repository_operation", allowed), ("bitbucket_write_refusal", allowed)):
        monkeypatch.setattr(bitbucket, name, value)
    monkeypatch.setattr(_bitbucket_internal_network, "_bitbucket_json_get", get)
    monkeypatch.setattr(bitbucket, "cloud_context", lambda _context: False)
    monkeypatch.setattr(bitbucket, "_repository", lambda params, _context: (
        params["project_key"], params["repo_slug"], None))
    result = await bitbucket.PostBitbucketPullRequestReview().execute(
        {"project_key": "SHOP", "repo_slug": "demo-shop", "pr_id": "12", "commit": SHA, "summary": f"{MARKER} new",
         "marker": MARKER, "comments": COMMENTS, "commit_status": STATUS}, CONTEXT)
    assert (result["summary"], result["summary_comment_id"], result["inline_posted"]) == ("updated", 31, 2)
    writes = [(method, path, body) for method, path, body, _ in api.calls if method != "GET"]
    assert writes[0] == ("PUT", f"{base}/comments/31", {"text": f"{MARKER} new", "version": 2})
    assert writes[2][2]["anchor"] == {"path": "pay/new.py", "line": 1, "lineType": "CONTEXT", "fileType": "TO",
                                      "diffType": "EFFECTIVE"}
    assert writes[3][1] == f"/rest/build-status/1.0/commits/{SHA}" and writes[3][2]["state"] == "FAILED"
    heads = await bitbucket.ListBitbucketPullRequestHeads().execute(
        {"project_key": "SHOP", "repo_slug": "demo-shop"}, CONTEXT)
    assert heads["pull_requests"][0] | {} == {
        "number": 12, "head_sha": SHA, "source_branch": "feature/PAY-1-totals", "target_branch": "main",
        "head_repository": "SHOP/demo-shop", "repository": "SHOP/demo-shop",
        "title": "Round totals half away from zero", "author": "anna", "draft": False,
        "url": "https://bitbucket.example.test/projects/SHOP/repos/demo-shop/pull-requests/12"}


async def test_a_status_without_an_https_link_is_not_sent_to_bitbucket(cloud_api):
    result = await bitbucket.PostBitbucketPullRequestReview().execute(
        {"project_key": "acme", "repo_slug": "payments", "pr_id": 7, "commit": SHA,
         "commit_status": {**STATUS, "target_url": ""}}, CONTEXT)
    assert "commit_status" not in result and cloud_api.calls == []
