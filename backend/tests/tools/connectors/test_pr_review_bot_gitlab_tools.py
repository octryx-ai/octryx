"""PR review bot, GitLab tools against recorded API v4 answers (no network): merge request reads, the summary
note, inline discussions, the ``octryx-review`` status and thread answers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.pr_review_bot.ci_results import ci_findings
from app.tools.connectors import gitlab_commit_checks as checks
from app.tools.connectors import gitlab_mr_review as gitlab

FIXTURES = Path(__file__).parents[2] / "fixtures" / "pr_review_bot"
SHA = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"
MARKER = "<!-- octryx-review-summary -->"
CONTEXT = SimpleNamespace(project_config={"gitlab_allowed_projects": ["acme/pay"]}, project_ids=["ws"], db=None,
                          user_id="bot")
BASE = "/projects/acme%2Fpay"
MR = f"{BASE}/merge_requests/42"
REFS = {"base_sha": "b" * 40, "start_sha": "5" * 40, "head_sha": SHA}
COMMENTS = [{"path": "pay/totals.py", "line": 7, "body": "fix\n\n```suggestion:-1+0\nx\n```", "line_type": "ADDED"},
            {"path": "pay/new.py", "line": 4, "old_line": 3, "body": "name it", "line_type": "CONTEXT"}]
STATUS = {"state": "failure", "description": "1 blocking finding(s): 1 high", "context": "octryx/review",
          "target_url": "https://octryx.example.test/chat?session_id=s1"}


def _refused(status: int, text: str) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(str(status), request=httpx.Request("POST", "https://x"),
                                 response=httpx.Response(status, text=text))


class Recorder:
    def __init__(self):
        self.answers, self.calls = {}, []

    async def http(self, method, url, *, headers=None, params=None, json_body=None, **_):
        path = url.removeprefix("https://gitlab.test/api/v4")
        self.calls.append((method, path, json_body, params))
        value = self.answers.get((method, path), {})
        if isinstance(value, Exception):
            raise value
        return value(params) if callable(value) else value

    def writes(self):
        return [(method, path, body, params) for method, path, body, params in self.calls if method != "GET"]


@pytest.fixture
def api(monkeypatch):
    recorder = Recorder()

    async def headers(_context):
        return {"PRIVATE-TOKEN": "test-token"}

    async def allowed(*_args, **_kwargs):
        return None

    for module in (gitlab, checks):
        monkeypatch.setattr(module, "_http_json", recorder.http)
        monkeypatch.setattr(module, "_gitlab_headers", headers)
        monkeypatch.setattr(module, "_gitlab_base_url", lambda _context: "https://gitlab.test/api/v4")
        monkeypatch.setattr(module, "require_gitlab_repository_operation", allowed)
    return recorder


async def test_open_heads_are_read_page_by_page_with_draft_and_fork(api):
    page = json.loads((FIXTURES / "gitlab_merge_requests_page.json").read_text())
    api.answers = {("GET", f"{BASE}/merge_requests"): lambda params: page * 34 if params["page"] == 1 else page}
    result = await gitlab.ListGitLabMergeRequestHeadsTool().execute({"project": "acme/pay"}, CONTEXT)
    assert len(result["pull_requests"]) == 105  # 102 on a full first page, 3 on the second: none cut
    assert api.calls[0][3] == {"state": "opened", "per_page": 100, "page": 1}
    ready, draft, fork = result["pull_requests"][:3]
    assert ready == {"number": 42, "head_sha": SHA, "source_branch": "feature/PAY-1-totals", "target_branch": "main",
                     "head_repository": "acme/pay", "repository": "acme/pay",
                     "title": "Round totals half away from zero", "author": "dev-anna",
                     "url": "https://gitlab.example.test/acme/pay/-/merge_requests/42", "draft": False}
    assert draft["draft"] is True and draft["head_repository"] == "acme/pay"
    assert fork["head_repository"] != "acme/pay" and fork["draft"] is False


async def test_notes_since_a_time_skip_system_notes_and_name_their_thread(api):
    page = json.loads((FIXTURES / "gitlab_merge_requests_page.json").read_text())[:1]
    api.answers = {("GET", f"{BASE}/merge_requests"): page,
                   ("GET", f"{MR}/discussions"): json.loads((FIXTURES / "gitlab_discussions.json").read_text()),
                   ("GET", f"{BASE}/members/all"): lambda params: [
                       {"username": "dev-anna-2", "access_level": 50},
                       {"username": params["query"], "access_level": 30 if params["query"] == "dev-anna" else 20}]}
    result = await gitlab.ListGitLabMergeRequestHeadsTool().execute(
        {"project": "acme/pay", "comments_since": "2026-11-20T09:00:00+00:00",
         "permissions_for": ["dev-anna", "dev-ben"]}, CONTEXT)
    assert [(item["id"], item["body"], item["in_reply_to"], item["inline"]) for item in result["comments"]] == [
        ("301", "@octryx review full", "", False),
        ("402", "@octryx explain", "6a9c1750b37d513a43987b574953fceb50b03ce7", True)]  # 401 is older, 302 system
    assert result["comments"][0] | {} == {"id": "301", "pr": "42", "author": "dev-anna", "author_id": "",
                                          "body": "@octryx review full", "created_at": "2026-11-20T09:10:00+00:00",
                                          "in_reply_to": "", "inline": False}
    assert result["permissions"] == {"dev-anna": "write", "dev-ben": "read"}  # Developer writes, Reporter reads


async def test_summary_is_edited_in_place_inline_anchored_on_diff_refs_and_status_set(api):
    api.answers = {("GET", f"{MR}/notes"): [{"id": 5, "body": "LGTM", "system": False},
                                            {"id": 9, "body": f"{MARKER}\nold", "system": False}],
                   ("PUT", f"{MR}/notes/9"): {"id": 9},
                   ("GET", MR): {"iid": 42, "diff_refs": REFS},
                   ("POST", f"{MR}/discussions"): {"id": "d" * 40}}
    result = await gitlab.PostGitLabMergeRequestReviewTool().execute(
        {"project": "acme/pay", "mr_iid": "42", "commit": SHA, "summary": f"{MARKER}\nnew", "marker": MARKER,
         "comments": COMMENTS, "commit_status": STATUS}, CONTEXT)
    assert (result["summary"], result["summary_comment_id"], result["inline_posted"], result["commit_status"]) == (
        "updated", 9, 2, "failed")
    assert result["inline_ids"] == ["d" * 40] * 2 and "inline_refused" not in result
    writes = api.writes()
    assert ("POST", f"{MR}/notes") not in [(method, path) for method, path, _b, _p in writes]  # never a second one
    assert writes[0][:3] == ("PUT", f"{MR}/notes/9", {"body": f"{MARKER}\nnew"})
    assert writes[1][2]["position"] == {"position_type": "text", **REFS, "new_path": "pay/totals.py",
                                        "old_path": "pay/totals.py", "new_line": 7}
    assert writes[1][2]["body"].endswith("```suggestion:-1+0\nx\n```")
    assert writes[2][2]["position"]["old_line"] == 3 and writes[2][2]["position"]["new_line"] == 4
    assert writes[3][:3] == ("POST", f"{BASE}/statuses/{SHA}", {
        "state": "failed", "name": "octryx-review", "description": "1 blocking finding(s): 1 high",
        "target_url": STATUS["target_url"]})


async def test_a_refused_position_keeps_the_other_comments_the_summary_and_the_status(api):
    answers = iter([_refused(400, '{"message":{"line_code":["can\'t be blank"]}}'), {"id": "e" * 40}])
    api.answers = {("GET", f"{MR}/notes"): [], ("POST", f"{MR}/notes"): {"id": 3}, ("GET", MR): {"diff_refs": REFS},
                   ("POST", f"{MR}/discussions"): lambda _params: _raise_or(next(answers))}
    result = await gitlab.PostGitLabMergeRequestReviewTool().execute(
        {"project": "acme/pay", "mr_iid": "42", "commit": SHA, "summary": "s", "marker": MARKER,
         "comments": COMMENTS, "commit_status": STATUS}, CONTEXT)
    assert (result["summary"], result["inline_posted"], result["inline_ids"]) == ("created", 1, [None, "e" * 40])
    assert "pay/totals.py:7" in result["inline_refused"] and result["commit_status"] == "failed"


def _raise_or(value):
    if isinstance(value, Exception):
        raise value
    return value


async def test_a_status_the_commit_already_has_is_not_a_failed_post(api):
    api.answers = {("POST", f"{BASE}/statuses/{SHA}"): _refused(
        400, '{"message":"Cannot transition status via :enqueue from :pending"}')}
    result = await gitlab.PostGitLabMergeRequestReviewTool().execute(
        {"project": "acme/pay", "mr_iid": "42", "commit": SHA,
         "commit_status": {"state": "pending", "description": "Octryx is reviewing"}}, CONTEXT)
    assert (result["status"], result["commit_status"], result["commit_status_unchanged"]) == ("posted", "pending", True)
    assert "target_url" not in api.calls[0][2]  # no https link: GitLab gets none
    api.answers[("POST", f"{BASE}/statuses/{SHA}")] = _refused(403, "forbidden")
    with pytest.raises(httpx.HTTPStatusError):  # any other refusal fails the post (the step names it)
        await gitlab.PostGitLabMergeRequestReviewTool().execute(
            {"project": "acme/pay", "mr_iid": "42", "commit": SHA, "commit_status": {"state": "success"}}, CONTEXT)


async def test_threads_reply_and_resolve_and_a_conversation_reply_is_a_note(api):
    thread = "6a9c1750b37d513a43987b574953fceb50b03ce7"
    api.answers = {("POST", f"{MR}/notes"): {"id": 77},
                   ("PUT", f"{MR}/discussions/bad"): _refused(403, "no")}
    result = await gitlab.PostGitLabMergeRequestReviewTool().execute(
        {"project": "acme/pay", "mr_iid": "42", "commit": SHA, "comment": "Octryx: paused.", "thread_answers": [
            {"comment_id": thread, "reply": "Fixed in c0ffee0.", "resolve": True},
            {"comment_id": "bad", "reply": "", "resolve": True},
            {"comment_id": "../../projects", "reply": "x"}]}, CONTEXT)
    assert result["comment_id"] == 77
    assert result["threads"] == [{"comment_id": thread, "replied": True, "resolved": True},
                                 {"comment_id": "bad", "replied": False, "resolved": False,
                                  "reason": "status_code 403"}]  # a path-like id is never sent
    writes = api.writes()
    assert writes[1][:3] == ("POST", f"{MR}/discussions/{thread}/notes", {"body": "Fixed in c0ffee0."})
    assert writes[2][1::2] == (f"{MR}/discussions/{thread}", {"resolved": "true"})


async def test_wrong_arguments_post_nothing(api):
    for arguments in ({"mr_iid": "42; DROP", "commit": SHA}, {"mr_iid": "42", "commit": "main"},
                      {"project": "other/repo", "mr_iid": "42", "commit": SHA}):
        result = await gitlab.PostGitLabMergeRequestReviewTool().execute({"project": "acme/pay", **arguments},
                                                                        CONTEXT)
        assert "error" in result
    assert api.calls == []


async def test_ci_is_the_latest_status_per_name_and_allowed_failures_never_block(api):
    url = f"{BASE}/repository/commits/{SHA}/statuses"
    api.answers = {("GET", url): [
        {"name": "test", "status": "failed", "stage": "test", "target_url": "https://gitlab.test/jobs/1",
         "description": None},
        {"name": "test", "status": "success", "stage": "test"},
        {"name": "lint", "status": "failed", "stage": "test", "allow_failure": True},
        {"name": "deploy", "status": "manual", "stage": "deploy"},
        {"name": "build", "status": "running", "stage": "build"},
        {"name": "octryx-review", "status": "pending"},
        {"name": "sonar", "status": "success"}]}
    answer = await checks.GetGitLabCommitChecksTool().execute({"project": "acme/pay", "commit": SHA}, CONTEXT)
    assert [(item["name"], item["kind"], item["state"]) for item in answer["checks"]] == [
        ("test", "job", "failure"), ("lint", "job", "other"), ("deploy", "job", "other"), ("build", "job", "pending"),
        ("octryx-review", "status", "pending"), ("sonar", "status", "success")]
    result = ci_findings("gitlab", answer)
    assert [item["id"] for item in result.findings] == ["CI1"] and result.pending == ["build"]  # never its own
    assert "'test' failed on this commit. https://gitlab.test/jobs/1" in result.findings[0]["fix"]
