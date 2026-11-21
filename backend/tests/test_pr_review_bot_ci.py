"""PR review bot, the reviewed commit's CI (red checks are findings, the bot never runs a repository's tests
itself).

- GitHub: the latest commit status per context (newest first) and every check run, page by page, in one shape;
- a failed check (GitHub failure/error/timed_out, Bitbucket FAILED/STOPPED) is a high finding ``CI<n>`` with its
  link; a running one is named; the bot's own ``octryx/review`` / ``octryx-review`` never counts;
- a failed check turns a passed review into "changes requested" with a "Blocking (CI)" line, shown as "CI" in the
  table; a CI that cannot be read is named in the footer and the review is still posted.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.pr_review_bot.actions import with_caller_findings
from app.services.pr_review_bot.ci_results import ci_findings
from app.services.pr_review_bot.render import build_post
from app.tools.connectors import github_commit_checks as checks

SHA = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"


async def test_github_reads_the_latest_status_per_context_and_every_check_run(monkeypatch):
    statuses = [{"context": "ci/tests", "state": "failure", "description": "2 failed", "target_url": "https://ci/1"},
                {"context": "ci/tests", "state": "pending"}, {"context": "octryx/review", "state": "pending"}]
    runs = {"check_runs": [{"name": "lint", "status": "completed", "conclusion": "success"},
                           {"name": "build", "status": "in_progress"},
                           {"name": "e2e", "status": "completed", "conclusion": "timed_out",
                            "html_url": "https://github.com/x/runs/9", "output": {"title": "timed out"}}]}
    calls = []

    async def http(method, url, *, headers=None, params=None, **_):
        calls.append(url.rsplit("/", 1)[-1])
        return statuses if url.endswith("/statuses") else runs

    async def allowed(*_args, **_kwargs):
        return None

    async def headers(_context):
        return {}

    monkeypatch.setattr(checks, "_http_json", http)
    monkeypatch.setattr(checks, "_github_headers", headers)
    monkeypatch.setattr(checks, "_github_base_url", lambda _context: "https://api.github.test")
    monkeypatch.setattr(checks, "require_github_repository_operation", allowed)
    context = SimpleNamespace(project_config={"github_allowed_repositories": ["acme/pay"]}, project_ids=["ws"])
    answer = await checks.GetGitHubCommitChecksTool().execute({"repository": "acme/pay", "commit": SHA}, context)
    assert [(item["name"], item["state"]) for item in answer["checks"]] == [
        ("ci/tests", "failure"), ("octryx/review", "pending"), ("lint", "success"), ("build", "pending"),
        ("e2e", "failure")]  # the newest status of ci/tests wins over its older pending one
    result = ci_findings("github", answer)
    assert [item["id"] for item in result.findings] == ["CI1", "CI2"] and result.pending == ["build"]
    assert "'ci/tests' failed on this commit: 2 failed. https://ci/1" in result.findings[0]["fix"]


def test_bitbucket_build_statuses_and_the_bots_own_status_never_counts():
    result = ci_findings("bitbucket", {"statuses": [
        {"key": "pipelines", "name": "Pipeline #7", "state": "FAILED", "url": "https://bb/7"},
        {"key": "octryx-review", "name": "Octryx review", "state": "FAILED"},
        {"key": "sonar", "name": "Sonar", "state": "INPROGRESS"}, {"key": "x", "name": "Old", "state": "STOPPED"}]})
    assert [item["fix"].split("'")[1] for item in result.findings] == ["Pipeline #7", "Old"]
    assert result.pending == ["Sonar"]


def test_a_failed_check_turns_a_passed_review_into_changes_with_a_ci_line_and_a_readable_table():
    red = ci_findings("bitbucket", {"statuses": [{"key": "p", "name": "Pipeline #7", "state": "FAILED"},
                                                 {"key": "q", "name": "Pipeline #8", "state": "FAILED"}]})
    review = with_caller_findings({"verdict": "pass", "summary": "Fine.", "findings": []}, red.findings)
    assert review["verdict"] == "changes" and len(review["findings"]) == 2  # two checks, both kept
    post = build_post(review, {}, provider="github", facts={"sha": SHA, "ci_pending": ["Sonar"],
                                                            "ci_unread": ""})
    # The red checks are named; the informing status (the default) leaves blocking to the CI's own checks.
    assert post.state == "success" and "**Blocking (CI):** 2 check(s) failed on this commit" in post.summary
    assert "| 🔴 High | CI | The CI check 'Pipeline #7' failed" in post.summary
    assert "> Reviewer: Fine." in post.summary and "CI still running: Sonar" in post.summary


def test_a_ci_that_cannot_be_read_is_named_and_the_review_still_stands():
    post = build_post({"verdict": "pass", "summary": "Fine.", "findings": []}, {}, provider="github",
                      facts={"sha": SHA, "ci_unread": "status_code 403"})
    assert post.state == "success" and "CI: status_code 403" in post.summary


async def test_a_token_that_cannot_read_check_runs_still_counts_the_statuses_and_says_so(monkeypatch):
    """A fine-grained token gets 403 on check runs; the footer must not show the raw error cut mid-word."""
    import httpx

    async def http(method, url, *, headers=None, params=None, **_):
        if url.endswith("/check-runs"):
            raise httpx.HTTPStatusError("403", request=httpx.Request("GET", url), response=httpx.Response(403))
        return [{"context": "ci/tests", "state": "failure", "description": "2 failed"}]

    async def allowed(*_args, **_kwargs):
        return None

    async def headers(_context):
        return {}

    monkeypatch.setattr(checks, "_http_json", http)
    monkeypatch.setattr(checks, "_github_headers", headers)
    monkeypatch.setattr(checks, "_github_base_url", lambda _context: "https://api.github.test")
    monkeypatch.setattr(checks, "require_github_repository_operation", allowed)
    context = SimpleNamespace(project_config={"github_allowed_repositories": ["acme/pay"]}, project_ids=["ws"])
    answer = await checks.GetGitHubCommitChecksTool().execute({"repository": "acme/pay", "commit": SHA}, context)
    result = ci_findings("github", answer)
    assert [item["id"] for item in result.findings] == ["CI1"]  # the statuses still count
    assert result.unread == ("check runs not readable with this token (GitHub App needed); commit statuses read: 1")


def test_a_long_reason_is_cut_at_a_word_boundary():
    from app.services.pr_review_bot.ci_results import short

    text = "Tool execution failed: Client error '403 Forbidden' for url 'https://api.github.com/x/check-runs' For more"
    cut = short(text, 60)
    assert cut.endswith("…") and len(cut) <= 61 and text.startswith(cut[:-1]) and not cut[:-1].endswith("Fo")
    assert short("short text") == "short text"
