"""Reviews converge and only real problems block.

Automatic revisions do not converge when every round is a fresh full audit; a foreign app's screenshot, other
stories' screens and self-computed contrast numbers must not produce findings; one cosmetic medium must not keep a
finished story from shipping."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.workflow_runs.auto_accept import accept_reason
from app.services.workflow_runs.review import screens
from app.services.workflow_runs.review.convergence import (
    Scope,
    changed_paths,
    previous_findings,
    settle_first,
    settle_follow_up,
)
from app.services.workflow_runs.review.verdict import Finding, parse_verdict
from tests.review_convergence_support import PNG, _finding

SCOPE = Scope(changed=("benchmark/src/profile.js", "benchmark/e2e/profile.spec.ts"), screens=("profile.png",))


def test_a_first_round_numbers_its_findings_and_drops_what_the_change_does_not_touch_unless_high(tmp_path):
    (tmp_path / "packmate").mkdir()
    (tmp_path / "packmate" / "members.js").write_text("x")
    scope = Scope(changed=SCOPE.changed, screens=SCOPE.screens, root=tmp_path)
    verdict = parse_verdict({"verdict": "changes", "summary": "s", "findings": [
        _finding("medium"), _finding("medium", "members-page.png", "Packmate header overlaps"),
        _finding("medium", "packmate/members.js"), _finding("high", "packmate/members.js", "breaks login"),
        _finding("low", "profile.png"), _finding("medium", "benchmark/src/new-file.js", "add the empty state")]})
    settled = settle_first(verdict, scope)
    assert [(item.id, item.file) for item in settled.verdict.findings] == [
        ("F1", "benchmark/src/profile.js"), ("F4", "packmate/members.js"), ("F5", "profile.png"),
        ("F6", "benchmark/src/new-file.js")]  # a file the change should add is in scope
    assert [(item["id"], item["dropped"]) for item in settled.dropped] == [("F2", "out_of_scope"),
                                                                          ("F3", "out_of_scope")]
    record = settled.record()
    assert record["findings"][0]["id"] == "F1" and parse_verdict(record) == settled.verdict


def test_a_changes_verdict_with_only_low_points_left_is_a_pass():
    verdict = parse_verdict({"verdict": "changes", "summary": "s", "findings": [_finding("low")]})
    assert settle_first(verdict, SCOPE).verdict.verdict == "pass"


def test_a_follow_up_answers_each_previous_id_and_new_points_count_only_when_high():
    previous = (Finding("medium", "benchmark/src/profile.js", 3, "add the empty state", "F1"),
                Finding("high", "benchmark/src/profile.js", 9, "save the profile", "F2"),
                Finding("medium", "benchmark/src/profile.js", 12, "show the error", "F3"))
    settled = settle_follow_up({"summary": "s", "previous": [
        {"id": "F1", "status": "fixed"}, {"id": "f2", "status": "not_fixed", "evidence": "profile.js:9"}],
        "findings": [_finding("medium", fix="spacing"), _finding("high", fix="the plan crashes"),
                     _finding("high", fix="save the profile", file="benchmark/src/profile.js")]}, previous, SCOPE)
    assert [(item.id, item.fix) for item in settled.verdict.findings] == [
        ("F2", "save the profile"), ("F3", "show the error"),  # F3 not answered: still open
        ("F4", "the plan crashes")]
    assert {item["fix"]: item["dropped"] for item in settled.dropped} == {"add the empty state": "fixed",
                                                                        "spacing": "new_not_high"}
    assert settled.verdict.verdict == "changes" and settled.record()["follow_up"][1]["evidence"] == "profile.js:9"
    everything = settle_follow_up({"previous": [{"id": "F2", "status": "fixed"}, {"id": "F3", "status": "fixed"},
                                                {"id": "F1", "status": "fixed"}], "findings": []}, previous, SCOPE)
    assert everything.verdict.verdict == "pass" and everything.verdict.findings == ()


def test_a_follow_up_still_reads_the_first_round_shape():
    previous = (Finding("medium", "a.js", 3, "add the empty state", "F1"),)
    assert settle_follow_up({"verdict": "pass", "summary": "ok", "findings": []}, previous, SCOPE
                            ).verdict.verdict == "pass"
    kept = settle_follow_up({"verdict": "changes", "summary": "no", "findings": [
        {"severity": "medium", "file": "a.js", "line": 5, "fix": "the empty state is still missing"}]}, previous, SCOPE)
    assert [item.id for item in kept.verdict.findings] == ["F1"]  # new medium wording: no new finding
    assert settle_follow_up({"summary": "no shape"}, previous, SCOPE) is None
    assert settle_follow_up({"previous": [], "findings": [{"severity": "huge"}]}, previous, SCOPE) is None


def test_previous_findings_come_only_from_the_same_nodes_changes_verdict():
    node = SimpleNamespace(id="review")
    run = SimpleNamespace(context={"review": {"node_id": "review", "verdict": "changes", "findings": [
        _finding("medium", fix="a"), _finding("high", fix="b", ident="F7")]}})
    assert [item.id for item in previous_findings(run, node)] == ["F1", "F7"]
    assert previous_findings(run, SimpleNamespace(id="spec_review")) == ()
    run.context["review"]["verdict"] = "pass"
    assert previous_findings(run, node) == ()


def test_changed_paths_reads_both_sides_of_a_diff():
    diff = "diff --git a/x.py b/x.py\n+1\ndiff --git a/old.js b/new.js\n"
    assert changed_paths(diff) == ("x.py", "old.js", "new.js")


def test_another_apps_screenshot_is_not_reviewed_with_this_change(tmp_path):
    """A screenshot of another app from the shared system test folder is not reviewed."""
    (tmp_path / "packmate" / "e2e").mkdir(parents=True)
    (tmp_path / "packmate" / "e2e" / "members.spec.ts").write_text(
        "await page.screenshot({ path: 'test-reports/screenshots/members-page.png' })")
    (tmp_path / "benchmark" / "e2e").mkdir(parents=True)
    shots = [screens.Screen(name, "image/png", PNG) for name in
             ("members-page.png", "profile.png", "packmate-home.png", "home.png", "plan.png")]
    changed = ("benchmark/src/profile.js", "benchmark/e2e/profile.spec.ts")
    kept = screens.of_change(shots, diff="+ await shot('plan')\n", changed=changed, root=tmp_path)
    assert [shot.name for shot in kept] == ["profile.png", "home.png", "plan.png"]  # unsure (home): kept
    assert screens.of_change(shots, diff="", changed=(), root=tmp_path) == shots  # no change known: all kept


def test_accept_after_the_revisions_needs_no_high_finding_and_every_task_verified():
    def run(findings, statuses=("verified",), verdict="changes"):
        tasks = [{"id": f"T{n}", "status": status} for n, status in enumerate(statuses, 1)]
        return SimpleNamespace(context={"review": {"verdict": verdict, "findings": findings}, "task_list": tasks})

    medium = [{"severity": "medium", "fix": "spacing"}, {"severity": "low", "fix": "wording"}]
    assert accept_reason(run(medium)) == ""  # before the revisions a medium still goes back to the agent
    assert accept_reason(run(medium), after_revisions=2) == (
        "no high finding after 2 automatic revisions; 2 medium or low findings are notes for the product owner, "
        "all 1 tasks verified")
    assert accept_reason(run([*medium, {"severity": "high", "fix": "x"}]), after_revisions=2) == ""
    assert accept_reason(run(medium, ("verified", "done")), after_revisions=2) == ""
    assert accept_reason(run(medium, ()), after_revisions=2) == ""
    assert accept_reason(run(medium, ()), needs_tasks=False, after_revisions=2) != ""
