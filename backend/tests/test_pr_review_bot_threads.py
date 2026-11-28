"""PR review bot: threads, debounce, superseded runs."""

from __future__ import annotations

import httpx
import pytest

from app.models import WorkflowRun
from app.services.pr_review_bot import webhook as bot_webhook
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.incremental import Effective
from app.services.pr_review_bot.render import InlineComment
from app.services.pr_review_bot.starter import TRIGGER_WEBHOOK, start_review
from app.services.pr_review_bot.threads import note, remember
from app.services.workflow_runs.review.runner import run_due_reviews
from app.tools.bitbucket_impl import _bitbucket_internal_network
from app.tools.bitbucket_impl import _bitbucket_pr_review as bitbucket
from app.tools.bitbucket_impl import _bitbucket_review_threads as bb_threads
from app.tools.connectors import github_pr_review as github
from tests.pr_review_bot_flow_support import HEADERS, REVIEW, _origin, _payload, _tools, _workspace
from tests.pr_review_bot_support import Recorder, cloud_api, github_api  # noqa: F401 - fixtures
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_pr_review_bot_incremental import _push
from tests.tools.bitbucket_impl.test_pr_review_bot_tools import COMMENTS, CONTEXT, SHA
from tests.workflow_run_review_support import ScriptedReviewer

pytestmark = pytest.mark.usefixtures("scripted_pool")

THREADS = "/graphql"


async def test_github_keeps_each_inline_comments_id_and_answers_and_resolves_threads(github_api):  # noqa: F811
    github_api.answers = {
        ("POST", "/repos/acme/pay/pulls/42/reviews"): {"id": 77},
        ("GET", "/repos/acme/pay/pulls/42/reviews/77/comments"): [
            {"id": 902, "path": "pay/new.py", "body": "name it"}, {"id": 901, "path": "pay/totals.py", "body": "fix"}],
        ("POST", "/repos/acme/pay/pulls/42/comments/901/replies"): {"id": 990},
        ("POST", "/repos/acme/pay/pulls/42/comments/905/replies"): httpx.HTTPStatusError(
            "403", request=httpx.Request("POST", "https://x"), response=httpx.Response(403)),
    }

    def graphql(body):
        if "reviewThreads" in body["query"]:
            return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "pageInfo": {"hasNextPage": False}, "nodes": [
                    {"id": "T1", "isResolved": False, "comments": {"nodes": [{"databaseId": 901}]}}]}}}}}
        return {"data": {"resolveReviewThread": {"thread": {"id": body["variables"]["id"], "isResolved": True}}}}

    original = github_api.answer

    def answer(method, path, body=None, params=None):
        if path != THREADS:
            return original(method, path, body, params)
        github_api.calls.append((method, path, body, params))
        return graphql(body)

    github_api.answer = answer
    result = await github.PostGitHubPullRequestReviewTool().execute(
        {"repository": "acme/pay", "pr_number": "42", "commit": SHA, "comments": COMMENTS, "thread_answers": [
            {"comment_id": "901", "reply": "✅ Fixed in `abc1234`.", "resolve": True},
            {"comment_id": "905", "reply": "Still open.", "resolve": False}]}, CONTEXT)
    assert result["inline_ids"] == [901, 902]
    assert result["threads"] == [{"comment_id": "901", "replied": True, "resolved": True},
                                 {"comment_id": "905", "replied": False, "resolved": False,
                                  "reason": "status_code 403"}]
    resolve = [body for method, path, body, _ in github_api.calls if path == THREADS and "resolveReviewThread" in body["query"]]
    assert resolve == [{"query": resolve[0]["query"], "variables": {"id": "T1"}}]


async def test_bitbucket_cloud_keeps_ids_replies_and_resolves(cloud_api, monkeypatch):  # noqa: F811
    base = "/repositories/acme/payments/pullrequests/7/comments"
    created = iter([{"id": 51}, {"id": 52}, {"id": 60}])
    cloud_api.answers = {("POST", base): lambda _params: next(created)}

    async def request(_context, method, path, *, params=None, payload=None):
        return cloud_api.answer(method, path, payload, params)

    monkeypatch.setattr(bb_threads, "cloud_request", request)
    result = await bitbucket.PostBitbucketPullRequestReview().execute(
        {"project_key": "acme", "repo_slug": "payments", "pr_id": 7, "commit": SHA, "comments": COMMENTS,
         "thread_answers": [{"comment_id": "40", "reply": "✅ Fixed in `abc1234`.", "resolve": True}]}, CONTEXT)
    assert (result["inline_ids"], result["inline_posted"]) == ([51, 52], 2)
    assert result["threads"] == [{"comment_id": "40", "replied": True, "resolved": True}]
    writes = [(method, path, body) for method, path, body, _ in cloud_api.calls]
    assert writes[-2:] == [("POST", base, {"content": {"raw": "✅ Fixed in `abc1234`."}, "parent": {"id": 40}}),
                           ("POST", f"{base}/40/resolve", None)]


async def test_bitbucket_server_resolves_by_version_and_names_a_server_without_thread_resolution(monkeypatch):
    base = "/rest/api/1.0/projects/P/repos/r/pull-requests/12"
    api = Recorder({("GET", f"{base}/comments/31"): {"id": 31, "version": 3, "text": "fix"},
                    ("PUT", f"{base}/comments/31"): {"id": 31, "version": 4, "threadResolved": True},
                    ("GET", f"{base}/comments/32"): {"id": 32, "version": 1, "text": "old"},
                    ("PUT", f"{base}/comments/32"): {"id": 32, "version": 2}})

    async def get(_context, path, *, params=None):
        return api.answer("GET", path, None, params)

    async def post(_context, path, *, payload):
        return api.answer("POST", path, payload), 201

    async def put(_context, path, *, payload):
        return api.answer("PUT", path, payload), 200

    for name, value in (("_bitbucket_json_post", post), ("_bitbucket_json_put", put)):
        monkeypatch.setattr(bb_threads, name, value)
    monkeypatch.setattr(_bitbucket_internal_network, "_bitbucket_json_get", get)
    done = await bb_threads.server_answers(CONTEXT, base, [
        {"comment_id": "31", "reply": "✅ Fixed.", "resolve": True}, {"comment_id": "32", "resolve": True}])
    assert done == [{"comment_id": "31", "replied": True, "resolved": True},
                    {"comment_id": "32", "replied": False, "resolved": False,
                     "reason": "this server cannot resolve threads"}]
    assert ("PUT", f"{base}/comments/31", {"text": "fix", "version": 3, "threadResolved": True}, None) in api.calls
    assert ("POST", f"{base}/comments", {"text": "✅ Fixed.", "parent": {"id": 31}}, None) in api.calls


def test_comment_ids_are_kept_per_finding_and_the_footer_names_what_failed():
    comments = [InlineComment("totals.py", 3, "b", finding_id="F1"), InlineComment("x.py", 1, "c", finding_id="F3")]
    kept = remember([{"id": "F1"}, {"id": "F2", "comment_id": "7"}, {"id": "F3"}], comments, [11, None],
                    [{"id": "F2", "replied": True, "resolve": False}])
    assert kept == [{"id": "F1", "comment_id": "11"}, {"id": "F2", "comment_id": "7", "answered": True},
                    {"id": "F3"}]
    assert note([{"resolve": True, "resolved": True}, {"resolve": True, "resolved": False,
                                                       "reason": "status_code 403"}]) == (
        "1 thread(s) resolved · 1 thread(s) not answered (status_code 403)")
    assert note([]) == ""


def test_a_finding_still_open_is_answered_once_never_on_every_push():
    from app.services.pr_review_bot.incremental import thread_answers

    review = {"follow_up": [{"id": "F1", "status": "fixed", "evidence": "totals.py:3 adds 0.5"},
                            {"id": "F2", "status": "not_fixed", "evidence": "rates.py unchanged"}], "findings": [
        {"id": "F2", "comment_id": "8", "carried": True}, {"id": "F4", "comment_id": "9", "carried": True,
                                                          "answered": True}]}
    passed = Effective(review, [{"id": "F1", "comment_id": "7"}], 2, 0)
    assert thread_answers(passed, "abcdef1234") == [
        {"comment_id": "7", "reply": "✅ Fixed in `abcdef1`. totals.py:3 adds 0.5", "resolve": True, "id": "F1"},
        {"comment_id": "8", "resolve": False, "id": "F2", "reply": "Still open after `abcdef1`. rates.py unchanged"}]


async def test_a_fixed_finding_gets_its_thread_resolved_on_the_next_pass(db, monkeypatch, tmp_path):
    clone, first = _origin(tmp_path)
    tools = _tools(monkeypatch, clone, post_github_pull_request_review=[
        {"status": "posted"}, {"status": "posted", "inline_ids": [4711]}, {"status": "posted"},
        {"status": "posted", "threads": [{"comment_id": "4711", "replied": True, "resolved": True}]},
        {"status": "posted"}])
    project_id, _record, _hook = await _workspace(db)
    started = await start_review(db, project_id, pull_request_event(_payload(first), HEADERS), trigger=TRIGGER_WEBHOOK)
    assert await run_due_reviews(db, model_factory=ScriptedReviewer(REVIEW).factory) == 1
    run = await db.get(WorkflowRun, started.run_id)
    await db.refresh(run)
    assert [(item["id"], item.get("comment_id")) for item in run.context["pr_review"]["open_findings"]] == [
        ("F1", "4711"), ("F2", None)]

    second = _push(tmp_path / "origin", clone, "def total(items):\n    subtotal = sum(items)\n"
                   "    return int(subtotal + 0.5)\n")
    await start_review(db, project_id, pull_request_event(_payload(second), HEADERS), trigger=TRIGGER_WEBHOOK)
    assert await run_due_reviews(db, model_factory=ScriptedReviewer({"summary": "F1 fixed.", "previous": [
        {"id": "F1", "status": "fixed", "evidence": "totals.py:3 adds 0.5"}, {"id": "F2", "status": "not_fixed"}],
        "findings": []}).factory) == 1
    posts = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"]
    assert posts[3]["thread_answers"] == [
        {"comment_id": "4711", "reply": f"✅ Fixed in `{second[:7]}`. totals.py:3 adds 0.5", "resolve": True}]
    assert "1 thread(s) resolved" in posts[4]["summary"]


async def test_a_run_whose_head_was_pushed_over_posts_only_its_status(db, monkeypatch, tmp_path):
    clone, first = _origin(tmp_path)
    tools = _tools(monkeypatch, clone)
    project_id, _record, _hook = await _workspace(db)
    older = await start_review(db, project_id, pull_request_event(_payload(first), HEADERS), trigger=TRIGGER_WEBHOOK)
    second = _push(tmp_path / "origin", clone, "def total(items):\n    return sum(items)\n")

    async def newer_push():
        await start_review(db, project_id, pull_request_event(_payload(second), HEADERS), trigger=TRIGGER_WEBHOOK)

    assert await run_due_reviews(db, model_factory=ScriptedReviewer(REVIEW, REVIEW, during=newer_push).factory) >= 1
    run = await db.get(WorkflowRun, older.run_id)
    await db.refresh(run)
    posted = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"
              and call[1]["commit"] == first][-1]
    assert set(posted) == {"repository", "pr_number", "commit", "commit_status"}
    assert posted["commit_status"]["description"].startswith("Superseded by a newer push · ")
    assert run.context["pr_review"]["superseded_by"] and not run.context["pr_review"].get("posted")


async def test_pushes_in_quick_succession_start_one_review(db, monkeypatch):
    project_id, _record, hook = await _workspace(db)
    started = []
    monkeypatch.setattr(bot_webhook, "_spawn", lambda coroutine: coroutine.close())

    async def no_wait(_seconds):
        return None

    async def start(_db, project, event, *, trigger):
        started.append(event.head_sha)
        return bot_webhook.StartOutcome("started", run_id="r")

    monkeypatch.setattr(bot_webhook, "_wait", no_wait)
    monkeypatch.setattr(bot_webhook, "start_review", start)
    for head in ("a" * 40, "b" * 40):
        assert await bot_webhook.on_scm_webhook(db, hook, _payload(head), HEADERS, is_test=False) == {
            "outcome": "queued"}

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_):
            return None

    for head in ("a" * 40, "b" * 40):
        await bot_webhook.start_in_background(project_id, pull_request_event(_payload(head), HEADERS),
                                              session_factory=Session)
    assert started == ["b" * 40]
