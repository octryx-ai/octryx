"""PR review bot: what became of its findings, counted when it happens, never queried; labels carry no name
or pull request number."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.models import WorkflowRun
from app.services.observability import review_bot_metrics as metrics
from app.services.pr_review_bot import outcomes
from app.services.pr_review_bot.incremental import reviewer_findings
from tests.pr_review_bot_flow_support import _workspace

DASHBOARD = Path(__file__).parents[4] / "deployment/grafana/octryx-agents.json"


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset()
    yield
    metrics.reset()


def _series() -> dict[tuple[str, ...], float]:
    return dict(metrics.OUTCOMES.series)


def test_the_labels_carry_no_free_text():
    key = metrics.repo_key("github:octryx-ai/review-bot-test")
    assert len(key) == 8 and "review" not in key and key == metrics.repo_key("GITHUB:octryx-ai/review-bot-test")
    metrics.count_outcome("github", "github:octryx-ai/review-bot-test", "critical", "fixed")
    metrics.count_outcome("github", "github:octryx-ai/review-bot-test", "high", "liked")  # unknown outcome: none
    assert _series() == {("github", key, "unknown", "fixed"): 1}
    rendered = "\n".join(metrics.OUTCOMES.render())
    assert "review-bot-test" not in rendered and "pr" not in metrics.OUTCOMES.labels


async def test_a_fixed_finding_counts_as_applied_when_its_suggestion_commit_is_in_the_delta(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q", "-b", "main")
    (root / "a.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (root / "a.py").write_text("x = 2\n")
    git("commit", "-qam", "Apply suggestions from code review")
    head = git("rev-parse", "HEAD")
    run = WorkflowRun(repository="github:acme/pay", context={})
    fixed = [{"id": "F1", "severity": "high", "suggested": True}, {"id": "F2", "severity": "low"}]
    await outcomes.count_pass(run, "github", fixed, str(root), base, head)
    key = metrics.repo_key("github:acme/pay")
    assert _series() == {("github", key, "high", "suggestion_applied"): 1, ("github", key, "low", "fixed"): 1}


def test_a_posted_suggestion_is_remembered_with_its_finding():
    kept = reviewer_findings([{"id": "F1", "severity": "high", "suggestion": "x = 1", "start_line": 3},
                              {"id": "F2", "severity": "low"}, {"id": "C1", "source": "caller_check"}])
    assert kept == [{"id": "F1", "severity": "high", "suggested": True}, {"id": "F2", "severity": "low"}]


async def test_open_findings_of_a_closed_pull_request_count_once(db):
    project_id, _record, _hook = await _workspace(db)
    db.add_all([WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="pr-review-bot", title="t",
                            requested_by="bot", repository="github:acme/pay", context={"pr_review": {
                                "pr_id": "7", "posted": {"state": "failure"},
                                "open_findings": [{"id": "F1", "severity": "high"}, {"id": "F2", "severity": "low"}]}}),
                WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="pr-review-bot", title="t",
                            requested_by="bot", repository="github:acme/pay", context={"pr_review": {
                                "pr_id": "8", "posted": {"state": "failure"},
                                "open_findings": [{"id": "F1", "severity": "medium"}]}})])
    await db.flush()
    assert await outcomes.count_closed(db, project_id, "github:acme/pay", {"8"}) == 2  # #7 left the open list
    assert await outcomes.count_closed(db, project_id, "github:acme/pay", {"8"}) == 0  # once
    key = metrics.repo_key("github:acme/pay")
    assert _series() == {("github", key, "high", "open_at_close"): 1, ("github", key, "low", "open_at_close"): 1}


def test_the_dashboard_shows_the_outcomes_and_the_precision():
    panels = {panel["title"]: panel for panel in json.loads(DASHBOARD.read_text())["panels"]}
    precision = panels["Precision: fixed or applied / (those + ignored)"]["targets"][0]["expr"]
    assert 'outcome=~"fixed|suggestion_applied|ignored"' in precision and "octryx_pr_review_bot" in precision
    assert "or vector(0)" in precision and "> 0)" in precision  # 0 before the first fix, no division by zero
    assert "octryx_pr_review_bot_finding_outcomes_total" in panels["Finding outcomes (range)"]["targets"][0]["expr"]


def test_a_posted_review_starts_every_outcome_series_at_zero():
    metrics.count_findings("github", [("high", "inline")], "github:acme/pay")
    metrics.count_findings("github", [], "github:acme/pay")  # idempotent
    key = metrics.repo_key("github:acme/pay")
    assert len(_series()) == 12 and set(_series().values()) == {0}
    assert ("github", key, "medium", "open_at_close") in _series()
    metrics.count_outcome("github", "github:acme/pay", "high", "fixed")
    assert _series()[("github", key, "high", "fixed")] == 1
    assert 'outcome="fixed"' in "\n".join(metrics.OUTCOMES.render())  # rendered from the first scrape on
