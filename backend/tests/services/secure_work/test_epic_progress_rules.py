"""Every lane of an Epic's child and the precedence between them."""

import pytest

from app.services.secure_work.epic_progress import ChildFacts, Lane, child_lane, rollup


@pytest.mark.parametrize(("facts", "expected"), [
    (ChildFacts(work_state="intake"), Lane("open", "intake")),
    (ChildFacts(work_state="ready_for_development"), Lane("open", "ready_for_development")),
    (ChildFacts(work_state="development"), Lane("in_progress", "development")),
    (ChildFacts(work_state="blocked"), Lane("in_progress", "blocked", needs_you=True)),
    (ChildFacts(work_state="intake", run_status="running", run_phase="Build"), Lane("in_progress", "Build")),
    (ChildFacts(work_state="intake", run_status="paused"), Lane("in_progress", "paused", needs_you=True)),
    (ChildFacts(work_state="intake", run_status="completed"), Lane("open", "intake")),
    (ChildFacts(work_state="review"), Lane("in_review", "review")),
    (ChildFacts(work_state="development", pr_status="open", build_status="failed"),
     Lane("in_review", "pull request open", checks="failed", needs_you=True)),
    (ChildFacts(work_state="development", pr_status="open", ci_state="succeeded"),
     Lane("in_review", "pull request open", checks="green")),
    (ChildFacts(work_state="development", pr_status="open", build_status="in_progress", ci_state="failed"),
     Lane("in_review", "pull request open", checks="running")),
    (ChildFacts(work_state="development", run_status="running", pr_status="merged"), Lane("done", "merged")),
    (ChildFacts(work_state="done", run_status="running", pr_status="open"), Lane("done", "done")),
    (ChildFacts(work_state="rejected"), Lane("done", "won't do")),
])
def test_each_child_gets_the_lane_of_its_first_matching_rule(facts, expected):
    assert child_lane(facts) == expected


def test_the_rollup_counts_every_lane_and_who_needs_you():
    lanes = [Lane("done", "merged"), Lane("in_review", "x", needs_you=True), Lane("open", "intake")]

    assert rollup(lanes) == {"done": 1, "in_review": 1, "in_progress": 0, "open": 1, "total": 3, "needs_you": 1}
