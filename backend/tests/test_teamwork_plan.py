"""Teamwork, the coordinator's work plan: concurrent items may not own overlapping paths, and a revision
keeps merged work, never touches a running item and retries stuck ones."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.teamwork.plan import (
    changes_nothing,
    overlaps,
    revise,
    revision_problems,
    validate_plan,
    write_paths,
)

ROLES = {"backend": {}, "frontend": {}, "docs": {"needs_proof": False}}


def _item(key: str, *, role: str = "backend", paths=None, depends_on=None, proofs=None, **extra) -> dict:
    # The item writes its own proof test: its test file is one of its paths.
    return {"id": key, "title": f"Build {key}", "role": role, "paths": [*(paths or [f"{key}/**"]), f"tests/test_{key}.py"],
            "depends_on": depends_on or [], "instructions": f"Build {key}.",
            "proofs": proofs if proofs is not None else [f"tests/test_{key}.py::test_{key}"], **extra}


def _problems(*items: dict, roles=ROLES) -> list[str]:
    return validate_plan({"contract": "GET /api/search -> [{id, name}]", "items": list(items)}, roles=roles)[1]


def test_a_valid_plan_is_recorded_with_its_items_normalized():
    record, problems = validate_plan({"contract": "API", "items": [
        _item("api", proofs=["./tests/test_api.py::test_api"]),
        _item("ui", role="frontend", depends_on=["api"], model="claude-haiku-5-5")]}, roles=ROLES)
    assert problems == []
    assert record["contract"] == "API"
    assert record["items"][0]["proofs"] == ["tests/test_api.py::test_api"]  # canonical test ids
    assert record["items"][1]["model"] == "claude-haiku-5-5" and record["items"][1]["depends_on"] == ["api"]


def test_every_problem_is_listed_at_once():
    problems = _problems(
        {"id": "Bad Id!", "role": "backend", "paths": ["a/**"], "instructions": "x", "proofs": ["t.py::t"]},
        _item("two", role="ops"),
        _item("three", depends_on=["missing", "three"]),
        _item("four", paths=["/etc/passwd", "../up/**"]),
        {**_item("five"), "instructions": ""},
        _item("six", proofs=[]),
        _item("seven", proofs=["not a test id"]),
    )
    text = "\n".join(problems)
    assert not any("circle" in problem for problem in problems)  # a self-dependency is named once, not as a cycle
    for expected in ("bad id!", "'ops' is not one of", "depends on 'missing'", "cannot depend on itself",
                     "'/etc/passwd'", "'../up/**'", "five: instructions", "six: proofs",
                     "'not a test id' is not a test id"):
        assert expected in text


def test_no_items_and_duplicate_ids_are_refused():
    assert _problems() == ["items: at least one item"]
    assert any("every item needs its own id" in problem for problem in _problems(_item("a"), _item("a")))


def test_a_role_without_proofs_may_omit_them():
    assert _problems(_item("readme", role="docs", proofs=[])) == []


def test_a_dependency_cycle_is_refused():
    problems = _problems(_item("a", depends_on=["c"]), _item("b", depends_on=["a"]), _item("c", depends_on=["b"]))
    assert any("circle through a, b, c" in problem for problem in problems)


@pytest.mark.parametrize("first, second", [
    ("server/**", "server/search/api.ts"),
    ("src/**", "src/api/**"),
    ("web/*.tsx", "web/App.tsx"),
])
def test_concurrent_items_may_not_own_overlapping_paths(first, second):
    problems = _problems(_item("a", paths=[first]), _item("b", paths=[second]))
    assert len(problems) == 1 and "a and b can run at the same time" in problems[0]


def test_dependent_items_may_share_paths_even_through_a_chain():
    assert _problems(_item("a", paths=["server/**"]), _item("b", paths=["server/**"], depends_on=["a"])) == []
    assert _problems(_item("a", paths=["x/**"]), _item("b", paths=["y/**"], depends_on=["a"]),
                     _item("c", paths=["x/**"], depends_on=["b"])) == []  # a is c's ancestor through b


def test_disjoint_concurrent_items_pass():
    assert _problems(_item("api", paths=["server/**"]), _item("ui", role="frontend", paths=["web/**"])) == []


def test_no_artificial_limit_on_the_number_of_items():
    items = [_item(f"i{index}", paths=[f"pkg{index}/**"]) for index in range(60)]
    assert _problems(*items) == []


def _split(**statuses: str) -> dict[str, dict]:
    return {key: {**_item(key), "status": status, "iteration": 1, "session_id": f"s-{key}"}
            for key, status in statuses.items()}


def _record(*items: dict) -> dict:
    return validate_plan({"contract": "", "items": list(items)}, roles=ROLES)[0]


def test_a_merged_unchanged_item_keeps_its_status_and_a_reopened_one_runs_again():
    current = _split(a="merged", b="merged")
    split = revise(current, _record(_item("a"), _item("b", reopen=True)))
    assert split["a"]["status"] == "merged"
    assert (split["b"]["status"], split["b"]["iteration"], split["b"]["session_id"]) == ("pending", 2, "s-b")


def test_a_reworded_merged_item_stays_merged_and_only_reopen_or_new_work_runs_it_again():
    reworded = revise(_split(a="merged"), _record({**_item("a"), "instructions": "Merged and fine; keep unchanged.",
                                                   "depends_on": [], "title": "Search API"}))
    assert (reworded["a"]["status"], reworded["a"]["iteration"]) == ("merged", 1)
    assert reworded["a"]["instructions"] == "Merged and fine; keep unchanged."  # the coordinator's latest words
    reopened = revise(_split(a="merged"), _record({**_item("a"), "instructions": "Page the results.", "reopen": True}))
    assert (reopened["a"]["status"], reopened["a"]["iteration"]) == ("pending", 2)
    more = revise(_split(a="merged"), _record(_item("a", proofs=["tests/test_a.py::test_a",
                                                                 "tests/test_a.py::test_paging"])))
    assert (more["a"]["status"], more["a"]["iteration"]) == ("pending", 2)  # a new proof is new work


def test_a_running_item_cannot_be_changed_or_removed():
    current = _split(a="running", b="pending")
    assert revision_problems(current, _record({**_item("a"), "instructions": "other"}, _item("b"))) == [
        "a: is running and cannot be changed; wait until it ends"]
    assert revision_problems(current, _record(_item("b"))) == [
        "a: is running and cannot be removed; wait until it ends"]
    assert revision_problems(current, _record(_item("a"), _item("c"))) == []  # b (not started) may go, c may come


def test_items_not_started_can_be_added_or_removed_and_stuck_ones_are_retried():
    split = revise(_split(a="pending", b="blocked", c="failed"), _record(_item("b"), _item("c"), _item("d")))
    assert set(split) == {"b", "c", "d"}
    assert split["d"]["status"] == "pending" and split["d"]["iteration"] == 1
    assert (split["b"]["status"], split["b"]["iteration"]) == ("pending", 2)
    assert split["b"]["reason"] == "retry after blocked"


def test_a_proof_outside_the_items_own_paths_is_refused_with_a_hint():
    shell = _item("frontend-shell", role="frontend", paths=["web/**"],
                  proofs=["tests/system/test_shell.py::test_nav"])
    problems = _problems(shell, _item("system", role="frontend", paths=["tests/system/**"],
                                      depends_on=["frontend-shell"], proofs=["tests/system/test_shell.py::test_nav"]))
    assert problems == ["frontend-shell: proof 'tests/system/test_shell.py::test_nav' is outside its paths, so it "
                        "cannot write that test: give this proof to the item that writes the test (or add the test "
                        "file to this item's paths)"]


@pytest.mark.parametrize(("given", "stored"), [
    (["src/kitchen-helper/api/"], ["src/kitchen-helper/api/**"]),
    (["src/kitchen-helper/api"], ["src/kitchen-helper/api", "src/kitchen-helper/api/**"]),
    (["Makefile", "src/app.py", "web/*.js"], ["Makefile", "Makefile/**", "src/app.py", "web/*.js"]),
])
def test_a_folder_path_names_the_files_inside_it(given, stored):
    from app.services.workflow_runs.protected_paths import path_matches

    raw = {"id": "api", "title": "API", "role": "backend", "paths": given, "instructions": "Build it.", "proofs": []}
    record, problems = validate_plan({"items": [raw]}, roles={"backend": {"needs_proof": False}})
    assert problems == [] and record["items"][0]["paths"] == stored
    if given[0].startswith("src/kitchen-helper/api"):
        assert any(path_matches("src/kitchen-helper/api/routes.py", path) for path in stored)


@pytest.mark.parametrize(("first", "second", "meet"), [
    ("src/**/*.py", "src/kitchen-helper/web/**", True),  # src/kitchen-helper/web/x.py matches both
    ("**/*.py", "web/**", True),
    ("src/kitchen-helper/*.py", "src/kitchen-helper/web/**", True),  # '*' crosses folders (fnmatch)
    ("src/**/*.py", "src/**/*.js", False),
    ("server/**", "web/**", False),
    ("tests/test_*.py", "tests/system/**", False),
    ("src/a.py", "src/a.py", True),
    ("src/a.py", "src/b.py", False),
])
def test_overlap_sees_globs_that_cross_folders(first, second, meet):
    assert overlaps(first, second) is meet and overlaps(second, first) is meet


def test_concurrent_items_with_crossing_globs_are_refused():
    problems = _problems(_item("core", paths=["src/**/*.py"]), _item("web", role="frontend", paths=["src/kitchen-helper/web/**"]))
    assert len(problems) == 1 and "core and web can run at the same time" in problems[0]


def test_a_dependent_item_appends_to_a_shared_file_of_the_item_it_depends_on():
    shell = _item("shell", role="frontend", paths=["web/app.js", "web/i18n.js", "web/shell/**"])
    profile = _item("profile", role="frontend", paths=["web/profile/**"], depends_on=["shell"],
                    appends_to=["web/app.js", "web/i18n.js"])
    record, problems = validate_plan({"items": [shell, profile]}, roles=ROLES)
    assert problems == []
    assert write_paths(record["items"][1]) == ["web/profile/**", "tests/test_profile.py", "web/app.js", "web/i18n.js"]


def test_appends_to_needs_the_owner_as_a_dependency_and_appenders_of_one_file_take_turns():
    shell = _item("shell", role="frontend", paths=["web/app.js"])
    stranger = _item("stranger", role="frontend", paths=["web/x/**"], appends_to=["web/app.js"])
    assert ("stranger: appends_to 'web/app.js' is no file of an item it depends on: name the item that owns it in "
            "depends_on, or own the file yourself") in _problems(shell, stranger)
    one = _item("one", role="frontend", paths=["web/one/**"], depends_on=["shell"], appends_to=["web/app.js"])
    two = _item("two", role="frontend", paths=["web/two/**"], depends_on=["shell"], appends_to=["web/app.js"])
    [problem] = _problems(shell, one, two)
    assert "one and two can run at the same time but both own web/app.js / web/app.js" in problem
    assert _problems(shell, one, {**two, "depends_on": ["shell", "one"]}) == []


def test_a_resubmitted_plan_that_changes_nothing_is_recognised():
    record, _ = validate_plan({"items": [_item("a"), _item("b")]}, roles=ROLES)
    merged = {item["id"]: {**item, "status": "merged", "iteration": 1} for item in record["items"]}
    assert changes_nothing(merged, record)
    assert not changes_nothing(merged, {"items": [{**record["items"][0], "reopen": True}, record["items"][1]]})
    assert changes_nothing(merged, {"items": [{**record["items"][0], "instructions": "Fix x."},
                                              record["items"][1]]})  # a reworded merged item is not reopened
    assert not changes_nothing(merged, {"items": record["items"][:1]})
    assert not changes_nothing({**merged, "b": {**merged["b"], "status": "failed"}}, record)
    without_field = {key: {k: v for k, v in item.items() if k != "appends_to"} for key, item in merged.items()}
    assert changes_nothing(without_field, record)  # a missing field equals its empty value
