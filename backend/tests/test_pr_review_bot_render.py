"""PR review bot, pure parts: webhook payloads read on all three platforms, the review as the pull request shows it."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.pr_review_bot.diff_lines import ADDED, CONTEXT, line_kind, parse_diff
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.render import MARKER, build_post
from app.services.pr_review_bot.sync import head_event
from app.services.workflow_runs.review.verdict import parse_verdict

FIXTURES = Path(__file__).parent / "fixtures" / "pr_review_bot"
SHA = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_an_opened_or_pushed_pull_request_is_one_event_on_every_platform():
    github = pull_request_event(_fixture("github_pull_request_synchronize.json"), {"X-GitHub-Event": "pull_request"})
    assert (github.repository, github.pr_id, github.head_sha, github.source_branch, github.target_branch) == (
        "github:acme/pay", "42", SHA, "feature/PAY-1-totals", "main")
    assert (github.fork, github.draft, github.author) == (False, False, "dev-anna")
    cloud = pull_request_event(_fixture("bitbucket_cloud_pullrequest_updated.json"),
                               {"X-Event-Key": "pullrequest:updated"})
    assert (cloud.repository, cloud.pr_id, cloud.head_sha) == ("bitbucket:acme/payments", "7", "c0ffee00c0ff")
    server = pull_request_event(_fixture("bitbucket_server_pr_from_ref_updated.json"), {})
    assert (server.repository, server.pr_id, server.head_sha, server.url) == (
        "bitbucket:SHOP/demo-shop", "12", SHA,
        "https://bitbucket.example.test/projects/SHOP/repos/demo-shop/pull-requests/12")


def test_closed_pull_requests_reviews_and_other_events_start_nothing():
    payload = _fixture("github_pull_request_synchronize.json")
    assert pull_request_event({**payload, "action": "closed"}, {"X-GitHub-Event": "pull_request"}) is None
    assert pull_request_event(payload, {"X-GitHub-Event": "pull_request_review"}) is None
    assert pull_request_event(_fixture("bitbucket_cloud_pullrequest_updated.json"),
                              {"X-Event-Key": "pullrequest:fulfilled"}) is None
    assert pull_request_event({**_fixture("bitbucket_server_pr_from_ref_updated.json"), "eventKey": "pr:merged"},
                              {}) is None


def test_a_fork_and_a_draft_are_named_from_the_webhook_and_from_the_sync_list():
    payload = _fixture("github_pull_request_synchronize.json")
    payload["pull_request"]["head"]["repo"]["full_name"] = "outsider/pay"
    payload["pull_request"]["draft"] = True
    event = pull_request_event(payload, {"X-GitHub-Event": "pull_request"})
    assert (event.fork, event.draft) == (True, True)
    from app.tools.connectors.github_pr_review import _head

    listed = [head_event("github:acme/pay", _head(pr)) for pr in _fixture("github_pulls_page.json")]
    assert [(item.pr_id, item.draft, item.fork) for item in listed] == [
        ("42", False, False), ("43", True, False), ("44", False, True)]


DIFF = """diff --git a/pay/totals.py b/pay/totals.py
index 1111111..2222222 100644
--- a/pay/totals.py
+++ b/pay/totals.py
@@ -5,4 +5,5 @@ def total(items):
     subtotal = sum(items)
-    return int(subtotal)
+    rounded = round(subtotal)
+    return rounded
     # end
diff --git a/pay/new.py b/pay/new.py
new file mode 100644
--- /dev/null
+++ b/pay/new.py
@@ -0,0 +1,2 @@
+A = 1
+B = 2
"""


def test_the_diff_names_each_new_side_line_and_the_files_changes():
    files = parse_diff(DIFF)
    assert line_kind(files, "pay/totals.py", 5) == CONTEXT
    assert (line_kind(files, "pay/totals.py", 6), line_kind(files, "pay/totals.py", 7)) == (ADDED, ADDED)
    assert line_kind(files, "pay/totals.py", 20) == "" and line_kind(files, "other.py", 1) == ""
    assert (files["pay/totals.py"].added, files["pay/totals.py"].removed, files["pay/new.py"].status) == (2, 1, "added")


REVIEW = {
    "verdict": "changes", "summary": "Rounding is still wrong for negatives.",
    "findings": [
        {"id": "F1", "severity": "high", "file": "pay/totals.py", "line": 7, "start_line": 6,
         "fix": "Round half away from zero.", "suggestion": "    rounded = int(subtotal + 0.5)\n    return rounded"},
        {"id": "F2", "severity": "medium", "file": "pay/rates.py", "line": 30, "fix": "Keep rates in sync."},
        {"id": "F3", "severity": "low", "file": "pay/new.py", "line": 1, "fix": "Name the constant."},
    ],
    "walkthrough": [{"file": "pay/totals.py", "change": "Rounds the subtotal before returning it."}],
}


def test_findings_on_diff_lines_are_inline_with_a_suggestion_and_the_rest_sit_in_the_summary():
    post = build_post(REVIEW, parse_diff(DIFF), provider="github", facts={"sha": SHA, "model": "claude-haiku-5-5",
                                                                           "route": "company", "run_id": "run-1"})
    assert [(item.path, item.line, item.start_line) for item in post.comments] == [
        ("pay/totals.py", 7, 6), ("pay/new.py", 1, 0)]
    assert "```suggestion\n    rounded = int(subtotal + 0.5)\n    return rounded\n```" in post.comments[0].body
    assert post.summary.startswith(MARKER) and "## Octryx review: changes requested" in post.summary
    assert "`pay/rates.py:30` | Keep rates in sync." in post.summary
    assert "| `pay/totals.py` | Rounds the subtotal before returning it. | +2 −1 |" in post.summary
    assert "| `pay/new.py` | added | +2 −0 |" in post.summary and "claude-haiku-5-5 (company route)" in post.summary
    assert (post.state, post.description) == (
        "success", "Informational: 2 finding(s) to look at: 1 high · 1 medium · 1 low")
    gated = build_post(REVIEW, parse_diff(DIFF), provider="github", facts={"sha": SHA, "status_policy": "gate"})
    assert (gated.state, gated.description) == ("failure", "2 blocking finding(s): 1 high · 1 medium · 1 low")
    lows = build_post({"verdict": "pass", "summary": "", "findings": [REVIEW["findings"][2]]}, parse_diff(DIFF),
                      provider="github", facts={"sha": SHA})
    assert (lows.state, lows.description) == ("success", "No blocking findings · 1 low")
    clean = build_post({"verdict": "pass", "summary": "", "findings": []}, {}, provider="github", facts={"sha": SHA})
    assert clean.description == "No blocking findings"
    assert post.placed == [("high", "inline"), ("medium", "summary"), ("low", "inline")]


def test_only_a_committed_secret_fails_the_informing_status():
    secret = {"id": "S1", "severity": "high", "file": "pay/new.py", "line": 1, "fix": "gitleaks found a secret",
              "source": "scan", "kind": "secrets"}
    post = build_post({"verdict": "changes", "findings": [secret]}, parse_diff(DIFF), provider="github",
                      facts={"sha": SHA})
    assert (post.state, post.description) == ("failure", "1 committed secret(s): remove and rotate")


def test_bitbucket_gets_the_suggestion_as_a_code_block_and_a_pass_is_success():
    post = build_post(REVIEW, parse_diff(DIFF), provider="bitbucket", facts={"sha": SHA})
    assert "Suggested change:\n\n```\n    rounded" in post.comments[0].body and "suggestion" not in post.comments[0].body
    passed = build_post({"verdict": "pass", "summary": "Fine.", "findings": [REVIEW["findings"][2]]},
                        parse_diff(DIFF), provider="bitbucket", facts={"sha": SHA})
    assert (passed.state, passed.description) == ("success", "No blocking findings · 1 low")
    assert "## Octryx review: looks good" in passed.summary


def test_a_suggestion_with_backticks_keeps_its_fence_closed():
    finding = {"severity": "low", "file": "pay/new.py", "line": 1, "fix": "Quote it.", "suggestion": "A = '```'"}
    post = build_post({"verdict": "pass", "findings": [finding]}, parse_diff(DIFF), provider="github",
                      facts={"sha": SHA})
    assert "````suggestion\nA = '```'\n````" in post.comments[0].body


def test_suggestion_and_walkthrough_are_optional_extras_of_the_verdict():
    verdict = parse_verdict(REVIEW)
    assert (verdict.findings[0].suggestion.startswith("    rounded"), verdict.findings[0].start_line) == (True, 6)
    assert verdict.walkthrough == (("pay/totals.py", "Rounds the subtotal before returning it."),)
    broken = {**REVIEW, "walkthrough": "all files", "findings": [
        {**REVIEW["findings"][0], "start_line": 99, "suggestion": 5}]}
    kept = parse_verdict(broken)
    assert kept is not None and (kept.findings[0].suggestion, kept.findings[0].start_line) == ("", 0)
    assert kept.walkthrough == ()
    plain = {"verdict": "changes", "summary": "x", "findings": [{"severity": "high", "file": "a.py", "line": 3,
                                                                  "fix": "y"}]}
    assert parse_verdict(plain).to_dict() == plain
