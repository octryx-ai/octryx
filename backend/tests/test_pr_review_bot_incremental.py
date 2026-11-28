"""PR review bot: incremental passes."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import WorkflowRun
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.incremental import delta_base, effective, seed
from app.services.pr_review_bot.render import build_post
from app.services.pr_review_bot.starter import TRIGGER_WEBHOOK, start_review
from app.services.workflow_runs.review.convergence import Scope, previous_findings, settle_follow_up
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.pr_review_bot_flow_support import HEADERS, REVIEW, _git, _origin, _payload, _tools, _workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_review_support import ScriptedReviewer

pytestmark = pytest.mark.usefixtures("scripted_pool")

BRANCH = "feature/PAY-1-totals"
OPEN = [{"id": "F1", "severity": "high", "file": "totals.py", "line": 3, "fix": "Round half away from zero."},
        {"id": "F2", "severity": "medium", "file": "rates.py", "line": 9, "fix": "Rates must round the same way."}]


def _push(origin: Path, clone: Path, text: str, *, amend: bool = False) -> str:
    _git(origin, "checkout", "-q", BRANCH)
    (origin / "totals.py").write_text(text)
    _git(origin, "commit", "-qa", *(["--amend", "--no-edit"] if amend else ["-m", "fix"]))
    head = _git(origin, "rev-parse", "HEAD")
    _git(origin, "checkout", "-q", "main")
    _git(clone, "fetch", "-q", "--force", "origin", "+refs/heads/*:refs/remotes/origin/*")
    return head


def _previous(head: str, merge_base: str, **more) -> dict:
    return {"reviewed_sha": head, "merge_base": merge_base, "target_branch": "main", "open_findings": OPEN, **more}


async def test_only_a_plain_continuation_of_the_last_reviewed_head_is_incremental(tmp_path):
    clone, first = _origin(tmp_path)
    origin = tmp_path / "origin"
    _git(clone, "fetch", "-q", "origin")
    base = _git(clone, "merge-base", "origin/main", f"origin/{BRANCH}")
    second = _push(origin, clone, "def total(items):\n    return round(sum(items) + 0)\n")
    root = str(clone)
    plain = await delta_base(root, "r1", _previous(first, base), head=second, merge_base=base, target="main")
    assert plain.incremental and plain.base == first
    reasons = [
        (await delta_base(root, "", {}, head=second, merge_base=base, target="main")).full_because,
        (await delta_base(root, "r1", _previous(first, base), head=second, merge_base=base,
                          target="release")).full_because,
        (await delta_base(root, "r1", _previous(first, "0" * 40), head=second, merge_base=base,
                          target="main")).full_because,
        (await delta_base(root, "r1", _previous(second, base), head=second, merge_base=base,
                          target="main")).full_because]
    assert reasons == ["first pass", "the target branch changed",
                       "the target branch was merged into the pull request or moved its merge base",
                       "the head was reviewed before"]
    rewritten = _push(origin, clone, "def total(items):\n    return 0\n", amend=True)
    forced = await delta_base(root, "r1", _previous(second, base), head=rewritten, merge_base=base, target="main")
    assert forced.full_because == "the history was rewritten (force push or rebase)"


def test_the_open_findings_become_the_review_nodes_previous_verdict():
    assert seed({"open_findings": []}) is None
    record = seed({"open_findings": [{**OPEN[0], "carried": True, "nonblocking": True}]})
    run = type("Run", (), {"context": {"review": record}})()
    node = type("Node", (), {"id": "independent_review"})()
    assert [(item.id, item.file, item.line) for item in previous_findings(run, node)] == [("F1", "totals.py", 3)]


def _follow_up(answer: dict, changed: tuple[str, ...], root: Path) -> dict:
    run = type("Run", (), {"context": {"review": seed({"open_findings": OPEN})}})()
    previous = previous_findings(run, type("Node", (), {"id": "independent_review"})())
    return settle_follow_up(answer, previous, Scope(changed, (), root)).record()


def test_what_the_follow_up_drops_for_convergence_the_pull_request_still_shows(tmp_path):
    (tmp_path / "rates.py").write_text("x = 1\n")
    record = _follow_up({"summary": "F1 is fixed.", "previous": [{"id": "F1", "status": "fixed"}], "findings": [
        {"severity": "medium", "file": "totals.py", "line": 4, "fix": "Name the rounding mode."}]},
        ("totals.py",), tmp_path)
    passed = effective(record, {"open_findings": OPEN})
    assert [item["id"] for item in passed.fixed] == ["F1"]
    by_id = {item["id"]: item for item in passed.review["findings"]}
    assert by_id["F2"]["carried"] and not by_id["F2"].get("nonblocking")
    assert by_id["F3"]["nonblocking"] and by_id["F3"]["severity"] == "medium"
    assert passed.review["verdict"] == "changes" and (passed.still_open, passed.new) == (1, 1)
    later = effective({"verdict": "pass", "summary": "", "findings": [{**by_id["F3"]}]},
                      {"open_findings": [by_id["F3"]]})
    assert later.review["verdict"] == "pass"


def test_the_summary_names_the_pass_and_open_findings_get_no_second_inline_comment():
    review = {"verdict": "pass", "summary": "Fixed.", "findings": [
        {"id": "F2", "severity": "low", "file": "totals.py", "line": 2, "fix": "Old note.", "carried": True},
        {"id": "F3", "severity": "medium", "file": "totals.py", "line": 3, "fix": "New point.", "nonblocking": True}]}
    from app.services.pr_review_bot.diff_lines import parse_diff

    diff = ("diff --git a/totals.py b/totals.py\n--- a/totals.py\n+++ b/totals.py\n@@ -1,3 +1,3 @@\n def total(x):\n"
            "-    a\n-    b\n+    c\n+    d\n")
    post = build_post(review, parse_diff(diff), provider="github", facts={"sha": "b" * 40, "incremental": {
        "from": "a" * 40, "fixed": [OPEN[0]], "still_open": 1, "new": 1}})
    assert post.state == "success" and [comment.line for comment in post.comments] == [3]
    assert "**Incremental pass** `aaaaaaa..bbbbbbb`: 1 fixed, 1 still open, 1 new." in post.summary
    assert "- ✅ `totals.py:3` Round half away from zero." in post.summary
    assert "Still open from earlier passes:" in post.summary and "| `totals.py:2` | Old note. |" in post.summary


async def _review(db, project_id: str, head: str, answer: dict) -> tuple[WorkflowRun, ScriptedReviewer]:
    started = await start_review(db, project_id, pull_request_event(_payload(head), HEADERS),
                                 trigger=TRIGGER_WEBHOOK)
    reviewer = ScriptedReviewer(answer)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    run = await db.get(WorkflowRun, started.run_id)
    await db.refresh(run)
    return run, reviewer


async def test_a_push_after_a_review_is_reviewed_incrementally_until_everything_is_fixed(db, monkeypatch, tmp_path):
    clone, first = _origin(tmp_path)
    origin = tmp_path / "origin"
    tools = _tools(monkeypatch, clone)
    project_id, _record, _hook = await _workspace(db)
    run, _reviewer = await _review(db, project_id, first, REVIEW)
    assert [item["id"] for item in run.context["pr_review"]["open_findings"]] == ["F1", "F2"]
    assert run.context["pr_review"]["incremental"] == {"full_because": "first pass", "previous_run": ""}

    second = _push(origin, clone, "def total(items):\n    subtotal = sum(items)\n    return int(subtotal + 0.5)\n")
    run2, reviewer = await _review(db, project_id, second, {
        "summary": "F1 is fixed.", "previous": [{"id": "F1", "status": "fixed"}, {"id": "F2", "status": "not_fixed"}],
        "findings": [{"severity": "medium", "file": "totals.py", "line": 3, "fix": "Negative totals round wrong."}]})
    system, task = reviewer.tasks[0]
    assert "This is a follow-up review" in system and '"id": "F2"' in task
    assert "-    return round(subtotal)\n+    return int(subtotal + 0.5)" in task
    assert "-    return int(subtotal)" not in task
    posted = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"][-1]
    assert posted["commit_status"]["state"] == "failure"
    assert f"`{first[:7]}..{second[:7]}`: 1 fixed, 1 still open, 1 new." in posted["summary"]
    assert [(item["line"], item["body"].split("\n")[0]) for item in posted["comments"]] == [
        (3, "**🟠 Medium** · F3")]
    assert "| `rates.py:9` | Rates must round the same way. |" in posted["summary"]
    assert run2.context["pr_review"]["incremental"]["previous_run"] == run.id

    third = _push(origin, clone, "def total(items):\n    subtotal = sum(items)\n    return int(subtotal + 0.5)\n# r\n")
    await _review(db, project_id, third, {"summary": "F2 is fixed.", "previous": [
        {"id": "F2", "status": "fixed"}, {"id": "F3", "status": "not_fixed"}], "findings": []})
    posted = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"][-1]
    assert posted["commit_status"]["state"] == "success"
    assert "1 fixed, 1 still open, 0 new." in posted["summary"] and posted["comments"] == []
