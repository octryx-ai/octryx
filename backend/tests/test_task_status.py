"""A status per task of a work item, set from what the platform can check."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.workflow_runs.run_card_parts import task_list_view
from app.services.workflow_runs.task_status import (
    CHANGES,
    DONE,
    IN_PROGRESS,
    OPEN,
    VERIFIED,
    after_build,
    after_pipeline,
    after_review,
    counts,
    seed,
)

ITEMS = [{"id": "T1", "text": "search API", "proof": "tests/a.py::test_search"},
         {"id": "T2", "text": "dish cards", "proof": "tests/system/b.py::test_cards"}]


def _change(*tests):
    lines = []
    for path, name in tests:
        lines += [f"diff --git a/{path} b/{path}", f"+def {name}(page):", "+    assert True"]
    return {"base": "a" * 40, "patch": "\n".join(lines) + "\n"}


def _statuses(items):
    return [item["status"] for item in items]


def test_a_new_list_starts_open_and_keeps_known_statuses():
    fresh = seed(ITEMS, None, "r1")
    assert _statuses(fresh) == [OPEN, OPEN]
    earlier = [{**ITEMS[0], "status": VERIFIED}, {**ITEMS[1], "proof": "tests/other.py::test_x", "status": DONE}]
    again = seed(ITEMS, earlier, "r2")
    assert _statuses(again) == [VERIFIED, OPEN]  # T2's proof changed: a new task


def test_a_build_moves_tasks_by_their_proof_and_the_gates():
    items = seed(ITEMS, None, "r1")
    half = _change(("tests/a.py", "test_search"))
    assert _statuses(after_build(items, half, passed=False, run_id="r1")) == [IN_PROGRESS, OPEN]
    assert _statuses(after_build(items, half, passed=True, run_id="r1")) == [DONE, OPEN]
    full = _change(("tests/a.py", "test_search"), ("tests/system/b.py", "test_cards"))
    assert _statuses(after_build(items, full, passed=True, run_id="r1")) == [DONE, DONE]
    assert after_build(items, {"truncated": True}, passed=True, run_id="r1") == items  # cannot judge


def test_the_review_sends_named_tasks_back_and_verifies_the_rest():
    done = after_build(seed(ITEMS, None, "r1"), _change(("tests/a.py", "test_search"),
                                                        ("tests/system/b.py", "test_cards")), passed=True, run_id="r1")
    reviewed = after_review(done, "changes", [{"severity": "high", "fix": "T2: no image area on the cards"}], "r1")
    assert _statuses(reviewed) == [DONE, CHANGES] and reviewed[1]["note"].startswith("T2:")
    # a failed pass keeps the review's verdict; a passed one carries the fix
    assert _statuses(after_build(reviewed, _change(("tests/a.py", "test_search"), ("tests/system/b.py", "test_cards")),
                                 passed=False, run_id="r1")) == [IN_PROGRESS, CHANGES]
    fixed = after_build(reviewed, _change(("tests/a.py", "test_search"), ("tests/system/b.py", "test_cards")),
                        passed=True, run_id="r1")
    assert _statuses(fixed) == [DONE, DONE] and "note" not in fixed[1]
    passed = after_review(fixed, "pass", [], "r1")
    assert _statuses(passed) == [VERIFIED, VERIFIED]
    assert counts(passed)[VERIFIED] == 2


def test_the_card_shows_each_task_with_its_status():
    items = after_review(seed(ITEMS, None, "r1"), "changes", [{"severity": "high", "fix": "T1: wrong scope"}], "r1")
    view = task_list_view(SimpleNamespace(context={"task_list": items}))
    assert [(row["id"], row["status"], row["done"]) for row in view] == [("T1", CHANGES, False), ("T2", OPEN, False)]
    assert view[0]["note"] == "T1: wrong scope"


def test_an_extended_existing_proof_test_counts():
    """The proof test comes from an earlier story and this story only extends its body."""
    from app.services.workflow_runs.task_list import missing_proofs

    patch = ("diff --git a/tests/system/test_shell.py b/tests/system/test_shell.py\n"
             "--- a/tests/system/test_shell.py\n+++ b/tests/system/test_shell.py\n"
             "@@ -40,6 +40,9 @@ def test_later_screens_show_coming_soon(page):\n"
             "     page.goto(url)\n+    expect(page.get_by_role('searchbox')).to_be_visible()\n"
             "@@ -80,3 +83,3 @@ def test_untouched(page):\n-    old()\n     context()\n")
    items = [{"id": "T24", "text": "x", "proof": "tests/system/test_shell.py::test_later_screens_show_coming_soon"},
             {"id": "T25", "text": "y", "proof": "tests/system/test_shell.py::test_untouched"}]
    assert missing_proofs(items, {"patch": patch}) == ["T25 (tests/system/test_shell.py::test_untouched)"]


def test_an_unchanged_existing_proof_test_that_passed_counts():
    """T7's proof is an earlier story's test, unchanged and green in the newest run."""
    from types import SimpleNamespace

    from app.services.workflow_runs.task_list import missing_proofs, passed_tests

    run = SimpleNamespace(context={"tests": {"runs": [
        {"results": {"tests/a.py::test_notice[chromium]": {"outcome": "failed"}}},
        {"results": {"tests/a.py::test_notice[chromium]": {"outcome": "passed"},
                     "tests/a.py::test_red": {"outcome": "failed"}}}]}})
    green = passed_tests(run)
    assert green == frozenset({"tests/a.py::test_notice"})
    items = [{"id": "T7", "text": "x", "proof": "tests/a.py::test_notice"},
             {"id": "T8", "text": "y", "proof": "tests/a.py::test_red"}]
    assert missing_proofs(items, {"patch": ""}, green) == ["T8 (tests/a.py::test_red)"]


def test_an_extended_test_whose_def_is_a_context_line_counts():
    """The hunk begins two lines above the def, so git's header names the import line and the def is an unchanged
    context line inside the hunk."""
    from app.services.workflow_runs.task_list import missing_proofs

    patch = ("diff --git a/tests/m/test_p.py b/tests/m/test_p.py\n--- a/tests/m/test_p.py\n+++ b/tests/m/test_p.py\n"
             "@@ -4,7 +4,9 @@ from benchmark.placeholders import SCREENS\n \n \n def test_notice_text_in_de_and_en():\n"
             "-    assert len(SCREENS) == 7\n+    assert SCREENS == ('home',)\n     for s in SCREENS:\n")
    items = [{"id": "T7", "text": "x", "proof": "tests/m/test_p.py::test_notice_text_in_de_and_en"}]
    assert missing_proofs(items, {"patch": patch}) == []


def test_the_pipeline_proves_a_task_by_its_test_passing_there_not_by_the_diff():
    """Existing or extended proof tests are not always recognisable in the diff, so the pipeline's own run is the
    proof. Proven + green is done; proven but red stays in progress; not proven opens."""
    from app.services.workflow_runs.task_list import proof_outcome, unproven

    results = {"tests/a.py::TestSearch::test_search": {"outcome": "passed"},
               "tests/system/b.py::test_cards[de]": {"outcome": "passed"},
               "tests/system/b.py::test_cards[en]": {"outcome": "failed"},
               "tests/c.py": {"outcome": "error", "scope": "collection"}}
    assert proof_outcome("tests/a.py::test_search", results) == "passed"  # inside a class, unchanged in the diff
    assert proof_outcome("tests/system/b.py::test_cards", results) == "failed"  # every parameter must pass
    assert proof_outcome("tests/c.py::test_x", results) == "error"  # the file did not collect
    assert proof_outcome("tests/d.py::test_y", results) == "not run"
    assert unproven(ITEMS, results) == ["T2 (tests/system/b.py::test_cards: failed)"]
    items = [{**ITEMS[0], "status": OPEN}, {**ITEMS[1], "status": DONE}]
    assert _statuses(after_pipeline(items, {"T1"}, green=False, run_id="r")) == [IN_PROGRESS, OPEN]
    assert _statuses(after_pipeline(items, {"T1", "T2"}, green=True, run_id="r")) == [DONE, DONE]
    changes = [{**ITEMS[0], "status": CHANGES, "note": "T1: fix"}, items[1]]
    assert _statuses(after_pipeline(changes, set(), green=False, run_id="r")) == [CHANGES, OPEN]
