"""A finding the change fixes only in part stays open with only what is left.

A medium like "The result is not rounded to 2 decimals … Also add tests" must not stay open whole after the rounding
came in. The follow-up may answer ``partly_fixed`` with ``remaining``: the finding keeps only that part, its thread
says what was fixed and what is left, and the reviewer is told that one finding is one problem."""

from app.services.pr_review_bot.incremental import effective, thread_answers
from app.services.workflow_runs.review.convergence import Scope, previous_findings, settle_follow_up
from app.services.workflow_runs.review.verdict import ANSWER_CONTRACT

COMBINED = ("The result is not rounded to 2 decimals, unlike order_total. Round the result. Also add tests for valid "
            "code, unknown code and rounding, since the change ships with none.")


def _previous():
    record = {"node_id": "independent_review", "verdict": "changes", "findings": [
        {"id": "F2", "severity": "medium", "file": "shop/pricing.py", "line": 36, "fix": COMBINED,
         "suggestion": "    return round(x, 2)", "start_line": 36}]}
    node = type("Node", (), {"id": "independent_review"})()
    return previous_findings(type("Run", (), {"context": {"review": record}})(), node)


def test_a_partly_fixed_finding_stays_open_with_only_its_remaining_part():
    settled = settle_follow_up({"summary": "s", "findings": [], "previous": [
        {"id": "F2", "status": "partly_fixed", "evidence": "apply_coupon now rounds to 2 decimals.",
         "remaining": "Add tests for a valid code, an unknown code and the rounding."}]},
        _previous(), Scope(changed=("shop/pricing.py",))).record()
    (kept,) = settled["findings"]
    assert (kept["id"], kept["severity"]) == ("F2", "medium")
    assert kept["fix"] == "Add tests for a valid code, an unknown code and the rounding."
    assert "suggestion" not in kept  # the old suggestion was for the part that is done
    assert settled["follow_up"][0]["remaining"].startswith("Add tests")


def test_partly_fixed_without_what_remains_counts_as_not_fixed():
    settled = settle_follow_up({"summary": "s", "findings": [], "previous": [
        {"id": "F2", "status": "partly_fixed", "evidence": "rounds now"}]}, _previous(), Scope()).record()
    assert settled["findings"][0]["fix"] == COMBINED and settled["follow_up"][0]["status"] == "not_fixed"


def test_the_thread_says_what_was_fixed_and_what_is_left():
    before = {"open_findings": [{"id": "F2", "severity": "medium", "file": "shop/pricing.py", "line": 36,
                                 "fix": COMBINED, "comment_id": "17", "answered": True}]}
    record = {"verdict": "changes", "summary": "s", "findings": [
        {"id": "F2", "severity": "medium", "file": "shop/pricing.py", "line": 36, "fix": "Add tests."}],
        "follow_up": [{"id": "F2", "status": "partly_fixed", "evidence": "It rounds now.", "remaining": "Add tests."}]}
    (answer,) = thread_answers(effective(record, before), "af9aaca0")
    assert answer == {"comment_id": "17", "resolve": False, "id": "F2",
                      "reply": "◐ Partly fixed in `af9aaca`. It rounds now. Still open: Add tests."}


def test_the_reviewer_is_told_one_finding_is_one_problem():
    assert "One finding is one problem: two problems are two findings" in ANSWER_CONTRACT
