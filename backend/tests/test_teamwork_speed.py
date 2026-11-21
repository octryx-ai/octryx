"""Team delivery made fast.

What slows a team run down:
- a re-plan after a red pipeline re-runs every item when the coordinator rewords the merged ones;
- system tests that wait for every other item run alone at the end;
- a red pipeline always costs a coordinator turn and a full re-plan;
- an item blocks on contract sections the coordinator cited but never wrote;
- with four device slots the main thread keeps one, so the fourth item waits.

Pinned here: test items start at once, a red pipeline reopens only the items that own what failed, the coordinator's
Stop holds back a plan whose items cite missing contract sections, and the run's main-thread platform turns take no
device slot.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.workflow_runs.teamwork import contract_gate, fixes
from app.services.workflow_runs.teamwork.plan import validate_plan
from tests.teamwork_engine_support import fake, finish_item, items_of  # noqa: F401  (``fake`` is a fixture)
from tests.test_team_delivery import _story_at_work, actions  # noqa: F401  (``actions`` is a fixture)

ROLES = {"backend": {}, "frontend": {}, "test": {"starts_at_once": True}}


def _item(key: str, role: str = "backend", *, depends_on=None, paths=None, appends_to=None) -> dict:
    return {"id": key, "title": key, "role": role, "depends_on": depends_on or [],
            "paths": [*(paths or [f"{key}/**"]), f"tests/test_{key}.py"], "appends_to": appends_to or [],
            "instructions": f"Build {key}.", "proofs": [f"tests/test_{key}.py::test_{key}"]}


# --- a red pipeline becomes fix items ------------------------------------------------------------------------------

UI_OUTPUT = """============================= test session starts ==============================
tests/test_ui.py::test_ui FAILED
tests/test_api.py::test_api PASSED
=================================== FAILURES ===================================
___________________________________ test_ui ____________________________________

    def test_ui():
>       assert render() == "Search"
E       AssertionError
/Users/sample/kitchen-helper/server/search.py:12: AssertionError
=========================== short test summary info ============================
FAILED tests/test_ui.py::test_ui - AssertionError
"""


def _red(*, failed=("tests/test_ui.py::test_ui",), output=UI_OUTPUT, unproven=()) -> dict:
    return {"state": "red", "reported_at": "2026-11-13T12:51:41", "unproven": list(unproven),
            "results": [{"command": "python -m pytest -v", "exit_code": 1, "failed_tests": list(failed),
                         "output_tail": output}]}


def _split(*keys: str) -> dict:
    return {key: {**_item(key, "frontend" if key == "ui" else "backend",
                          paths=["server/**"] if key == "api" else ["web/**"] if key == "ui" else None),
                  "status": "merged", "iteration": 1, "session_id": f"s-{key}"} for key in keys}


async def _red_pipeline(db, run, red: dict) -> None:
    from app.services.workflow_runs.engine import resolve_current_node

    assert run.current_node_id == "pipeline"
    run.context = {**run.context, "pipeline": red}
    await resolve_current_node(db, run, "failed", actor_id=None)


# --- the contract gate ----------------------------------------------------------------------------------------------

CONTRACT = """# CHEF-9 Search

## 1 Goal and acceptance criteria
AC1. ...
## 2 Interface contract
### 2.1 Corpus format
### 2.1a Corpus errors
### 2.4 Search API
## 3. Decisions
A13. the closest kcal first (4.2)
"""


def _patch(text: str, *, new: bool = True) -> str:
    lines = "".join(f"+{line}\n" for line in text.splitlines())
    mode = "new file mode 100644\nindex 0000000..1111111\n" if new else "index 1111111..2222222 100644\n"
    return (f"diff --git a/docs/stories/CHEF-9.md b/docs/stories/CHEF-9.md\n{mode}--- /dev/null\n"
            f"+++ b/docs/stories/CHEF-9.md\n@@ -0,0 +1,{len(text.splitlines())} @@\n{lines}")


def _run_with_plan(instructions: str) -> SimpleNamespace:
    record = {"contract": "", "items": [{"id": "corpus-code", "instructions": instructions}]}
    return SimpleNamespace(context={"outputs": {"work_plan": {"record": record, "version": 1}}})


# --- test items write their tests from the contract while the others build -------------------------------------


def test_a_test_item_never_waits_for_the_items_it_tests():
    """System tests that depend on all other items run alone after the last merge; test items start at once."""
    api, ui = _item("api"), _item("ui", "frontend")
    waiting = _item("system", "test", depends_on=["api", "ui"], paths=["tests/system/**"])
    _record, problems = validate_plan({"items": [api, ui, waiting]}, roles=ROLES)
    assert problems == ["system: a test item writes its tests from the contract while the other items build, so it "
                        "does not wait for api, ui: drop them from depends_on (the pipeline runs its tests on the "
                        "merged story; only the owner of a shared file it appends to may stay)"]
    at_once = {**waiting, "depends_on": []}
    assert validate_plan({"items": [api, ui, at_once]}, roles=ROLES)[1] == []
    # The owner of a shared file it adds to (the root conftest) may stay a dependency.
    shared = {**_item("api"), "paths": ["api/**", "tests/conftest.py", "tests/test_api.py"]}
    appending = {**waiting, "depends_on": ["api"], "appends_to": ["tests/conftest.py"]}
    assert validate_plan({"items": [shared, ui, appending]}, roles=ROLES)[1] == []


def test_a_failing_test_goes_to_the_item_whose_code_its_failure_points_into():
    assigned, unassigned = fixes.assign(_split("api", "ui", "docs"), _red())
    assert unassigned == [] and list(assigned) == ["api"]
    assert assigned["api"][0]["what"].startswith("tests/test_ui.py::test_ui failed")
    assert "server/search.py:12" in assigned["api"][0]["output"]


def test_a_failing_test_without_a_pointer_goes_to_the_owner_of_the_test_and_proofs_to_their_item():
    output = UI_OUTPUT.replace("/Users/sample/kitchen-helper/server/search.py:12: AssertionError", "E   assert 1 == 2")
    assigned, unassigned = fixes.assign(_split("api", "ui"), _red(output=output, unproven=[
        "api (tests/test_api.py::test_paging: not run)"]))
    assert unassigned == [] and set(assigned) == {"api", "ui"}
    assert assigned["api"] == [{"what": "proof tests that did not pass in the pipeline: "
                                        "tests/test_api.py::test_paging: not run"}]
    assert assigned["ui"][0]["what"] == "tests/test_ui.py::test_ui failed in `python -m pytest -v`"


def test_what_no_item_owns_is_left_for_the_coordinator():
    _assigned, unassigned = fixes.assign(_split("api", "ui"), _red(failed=("tests/legacy/test_old.py::test_x",),
                                                                   output="E   assert 1 == 2\n"))
    assert unassigned == ["tests/legacy/test_old.py::test_x failed in python -m pytest -v and no item owns its test "
                          "or the code it names"]


def test_only_the_items_with_a_fix_run_again():
    split = fixes.reopen_for_fixes(_split("api", "ui"), {"api": [{"what": "x failed", "output": "trace"}]})
    assert (split["api"]["status"], split["api"]["iteration"], split["api"]["session_id"]) == ("pending", 2, "s-api")
    assert split["api"]["fix"] == [{"what": "x failed", "output": "trace"}]
    assert split["api"]["reason"] == f"{fixes.REASON}: x failed"
    assert (split["ui"]["status"], split["ui"]["iteration"]) == ("merged", 1)


@pytest.mark.asyncio
async def test_a_red_pipeline_reopens_only_the_owning_item_and_goes_back_to_the_pipeline(db, fake, actions):  # noqa: F811
    """The whole loop on the seed: red → the team node → api alone runs again with the failure → merged → the
    pipeline once more; ui is never started again and no coordinator turn happens."""
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.phase_marker import RUN_PHASE_CONTRACT_KEY
    from app.services.workflow_runs.teamwork.item_definition import item_definition

    run, _session, _plan = await _story_at_work(db, fake)
    for name in ("api", "ui"):
        await finish_item(db, run, name)
    started_before = list(fake.started)
    await _red_pipeline(db, run, _red())

    assert run.current_node_id == "work"
    items = items_of(run)
    assert (items["api"]["status"], items["api"]["iteration"]) == ("running", 2)
    assert (items["ui"]["status"], items["ui"]["iteration"]) == ("merged", 1)
    assert [name for name, _ in fake.started[len(started_before):]] == ["api"]
    node = (await graph_for_run(db, run)).nodes["work"]
    facts = item_definition(run, node, items["api"])["workflow_contract"][RUN_PHASE_CONTRACT_KEY]
    assert facts["pipeline_fix"]["failures"][0]["what"].startswith("tests/test_ui.py::test_ui failed")
    assert "This item was sent back to you: the CI pipeline on the merged story is red in your part" in " ".join(
        facts["findings"])

    await finish_item(db, run, "api")
    assert run.current_node_id == "pipeline" and actions[-1] == "pipeline.run"
    assert run.loop_counters["e-pipeline-red"]["used"] == 1


@pytest.mark.asyncio
async def test_a_red_pipeline_no_item_owns_goes_to_the_coordinator(db, fake, actions):  # noqa: F811
    run, _session, _plan = await _story_at_work(db, fake)
    for name in ("api", "ui"):
        await finish_item(db, run, name)
    await _red_pipeline(db, run, _red(failed=("tests/legacy/test_old.py::test_x",), output="E   assert 1 == 2\n"))
    assert run.current_node_id == "plan"
    lines = [entry["description"] for entry in run.gate_results["work"]["results"]]
    assert lines == ["The CI pipeline is red and no item owns it: tests/legacy/test_old.py::test_x failed in "
                     "python -m pytest -v and no item owns its test or the code it names"]
    assert {key: item["status"] for key, item in items_of(run).items()} == {"api": "merged", "ui": "merged"}


def test_the_sections_an_item_cites_are_read_from_its_instructions():
    text = ("Build corpus.py per contract 2.1 and the binding 2.1a; story contract sections 3.1, 3.3 and 5; "
            "screens per contract 2.5/2.6; Spec 6.1 is the specification, not the contract; see §2.4 and "
            "sections 7 and 8 of docs/stories/CHEF-9.md.")
    assert contract_gate.cited_sections(text) == ["2.1", "3.1", "3.3", "5", "2.5", "2.6", "7", "8", "2.4"]
    assert {"1", "2", "2.1", "2.1a", "2.4", "3"} <= contract_gate.contract_sections(CONTRACT)


def test_the_coordinators_stop_holds_a_plan_whose_items_cite_missing_contract_sections():
    """An item must not block on contract sections the coordinator cited but never wrote."""
    run = _run_with_plan("Build corpus.py per contract 2.1, 3.1 and 5.")
    result = contract_gate.contract_gap_result(run, {"patch": _patch(CONTRACT)})
    assert result.blocking and result.outcome == "failed"
    assert "3.1 (cited by corpus-code); 5 (cited by corpus-code)" in result.description
    assert contract_gate.contract_gap_result(_run_with_plan("per contract 2.1 and 2.4"),
                                             {"patch": _patch(CONTRACT)}) is None


def test_the_gate_judges_only_a_contract_whose_whole_text_it_sees():
    run = _run_with_plan("per contract 9.9")
    assert contract_gate.contract_gap_result(run, {"patch": _patch(CONTRACT, new=False)}) is None  # an edit only
    assert contract_gate.contract_gap_result(run, {"patch": _patch(CONTRACT), "truncated": True}) is None
    assert contract_gate.contract_gap_result(run, {"patch": "diff --git a/x.py b/x.py\nnew file mode 100644\n"}) is None
    assert contract_gate.contract_gap_result(run, None) is None
