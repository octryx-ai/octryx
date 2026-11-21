"""Test-contract semantics: every contract test is ``new`` or ``regression``.

Tests first may write new tests (red on their assertions) next to existing tests of a regression criterion (green);
a red gate that requires *every* confirmed test to fail would fail on the green ones (``does not fail``) until the
run pauses at its loop limit. The repository's declared test command (with ``--junitxml``) is allowed in Tests first.
"""

from __future__ import annotations

import pytest

from app.services.workflow_checks.library import TurnEvidence, evaluate_checks
from app.services.workflow_checks.test_results import all_red
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.test_runs import gate_fields, record_turn_test_runs
from tests.phased_seed_definitions import seed_definitions
from tests.test_workflow_run_hitl import _item, _start, contract_definition, drafted_plan, reach_contract
from tests.workflow_run_octryx_support import ROOT, _bound_run, _decide, _fix_definition, _hook

FILE = "tests/test_textkit.py"
NEW = [f"{FILE}::test_slugify_{name}" for name in (
    "lowercases", "replaces_spaces", "strips_punctuation", "collapses_dashes", "trims_dashes", "keeps_digits",
    "empty_string", "unicode_letters", "max_length")]
REGRESSION = [f"{FILE}::test_normalize_whitespace_collapses_and_trims", f"{FILE}::test_normalize_whitespace_empty"]
LIVE_CRITERIA = [
    {"id": "AC1", "text": "slugify turns a title into a URL slug", "command": f"python -m pytest -v {FILE}",
     "tests": [{"id": test_id, "role": "new"} for test_id in NEW]},
    {"id": "AC2", "text": "normalize_whitespace keeps working", "command": f"python -m pytest -v {FILE}",
     "tests": [{"id": test_id, "role": "regression"} for test_id in REGRESSION]},
]
DECLARED_TEST = "python -m pytest -v tests/ --junitxml=test-reports/report.xml"


def _run_of(results: dict[str, str]) -> dict:
    return {"source": "octryx", "all_green": all(value == "passed" for value in results.values()),
            "results": {test_id: {"outcome": outcome, "message": "assert 'a b' == 'a-b'" if outcome == "failed"
                                  else ""} for test_id, outcome in results.items()}}


LIVE_RED = _run_of({**{test_id: "failed" for test_id in NEW}, **{test_id: "passed" for test_id in REGRESSION}})
RED_CHECK = [{"type": "tests_red", "params": {}, "blocking": True, "description": "Red"}]


async def _confirmed_live_contract(client, auth_headers, db):
    item = await _item(db)
    _admin, run, session = await _start(db, contract_definition(), work_item_id=item.id)
    await reach_contract(db, run, session, LIVE_CRITERIA)
    await db.commit()
    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    confirmed = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                  json={"action": "confirm", "payload_hash": view["waiting"]["payload_hash"]})
    assert confirmed.status_code == 200, confirmed.text
    await db.refresh(run)
    return run, view["waiting"]["payload"]


@pytest.mark.asyncio
async def test_the_live_case_nine_new_red_and_two_regression_green_passes_the_red_gate(client, auth_headers, db):
    run, payload = await _confirmed_live_contract(client, auth_headers, db)
    # The confirmation showed every test's role; the confirm bound them.
    assert payload["test_roles"] == {**dict.fromkeys(NEW, "new"), **dict.fromkeys(REGRESSION, "regression")}
    plan = await drafted_plan(db, run)
    assert plan.acceptance_criteria_json[1]["test_roles"] == dict.fromkeys(REGRESSION, "regression")
    assert run.context["confirmed_test_roles"] == payload["test_roles"]

    await record_turn_test_runs(db, run, [LIVE_RED], node_id="work")
    fields = gate_fields(run)
    assert fields["red_seen"] is True  # red by role: green on a new test would come after this
    [result] = evaluate_checks(RED_CHECK, TurnEvidence(**fields))
    assert result.outcome == "passed", result.detail


@pytest.mark.asyncio
async def test_a_regression_test_failing_in_the_red_run_fails_the_red_gate(client, auth_headers, db):
    run, _payload = await _confirmed_live_contract(client, auth_headers, db)
    broken = _run_of({**{test_id: "failed" for test_id in NEW}, REGRESSION[0]: "failed", REGRESSION[1]: "passed"})
    await record_turn_test_runs(db, run, [broken], node_id="work")
    fields = gate_fields(run)
    assert fields["red_seen"] is False
    [result] = evaluate_checks(RED_CHECK, TurnEvidence(**fields))
    assert result.outcome == "failed" and "regression test does not pass" in result.detail
    assert REGRESSION[0] in result.detail
    # A regression test the run does not report is not seen, either.
    [unseen] = evaluate_checks(RED_CHECK, TurnEvidence(**{**fields, "test_runs": [_run_of(dict.fromkeys(NEW,
                                                                                                         "failed"))]}))
    assert unseen.outcome == "failed" and "not seen" in unseen.detail


def test_red_by_role_and_the_rule_before_roles():
    roles = {**dict.fromkeys(NEW, "new"), **dict.fromkeys(REGRESSION, "regression")}
    assert all_red(LIVE_RED, NEW + REGRESSION, roles) == (True, "")
    ok, why = all_red(LIVE_RED, NEW + REGRESSION)  # a contract confirmed before roles: every test is new
    assert not ok and "does not fail" in why
    still_green = _run_of({**{test_id: "failed" for test_id in NEW[1:]}, NEW[0]: "passed",
                           **{test_id: "passed" for test_id in REGRESSION}})
    ok, why = all_red(still_green, NEW + REGRESSION, roles)
    assert not ok and NEW[0] in why and "new test must fail" in why
    ok, why = all_red(LIVE_RED, REGRESSION, dict.fromkeys(REGRESSION, "regression"))
    assert not ok and "no new confirmed test" in why


@pytest.mark.asyncio
async def test_a_new_test_the_branch_already_passes_is_refused_at_submit(db):
    item = await _item(db)
    _admin, run, _session = await _start(db, contract_definition(), work_item_id=item.id)
    await record_turn_test_runs(db, run, [_run_of(dict.fromkeys(REGRESSION, "passed"))], node_id="clarify")

    criteria = [{**LIVE_CRITERIA[0], "tests": [{"id": REGRESSION[0], "role": "new"}, {"id": NEW[0], "role": "new"}]}]
    refused = await submit_output(db, run, "submit_test_contract", {"criteria": criteria})
    assert (refused["state"], refused["reason"]) == ("refused", "invalid_output")
    assert f"{REGRESSION[0]} is marked new but already passes on the branch" in refused["message"]

    unknown = await submit_output(db, run, "submit_test_contract", {"criteria": [
        {**LIVE_CRITERIA[0], "tests": [{"id": NEW[0], "role": "flaky"}]}]})
    assert unknown["state"] == "refused" and "role is new or regression" in unknown["message"]
    twice = await submit_output(db, run, "submit_test_contract", {"criteria": [
        LIVE_CRITERIA[0], {**LIVE_CRITERIA[1], "tests": [{"id": NEW[0], "role": "regression"}]}]})
    assert twice["state"] == "refused" and "one test has one role" in twice["message"]

    # A plain id leaves the role to the server: seen passing → regression, not seen → new.
    derived = await submit_output(db, run, "submit_test_contract", {"criteria": [
        {**LIVE_CRITERIA[0], "tests": [REGRESSION[0], NEW[0]]}]})
    assert derived["state"] == "recorded", derived
    recorded = run.context["outputs"]["test_contract"]["record"]["criteria"][0]
    assert recorded["test_roles"] == {REGRESSION[0]: "regression", NEW[0]: "new"}


@pytest.mark.asyncio
async def test_a_new_test_seen_passing_before_the_confirmation_blocks_the_confirm(client, auth_headers, db):
    item = await _item(db)
    _admin, run, session = await _start(db, contract_definition(), work_item_id=item.id)
    await reach_contract(db, run, session, LIVE_CRITERIA)
    await db.commit()
    stale_hash = run.node_state["waiting"]["payload_hash"]
    # The branch shows a "new" test passing before Tests first changed anything: it cannot be new.
    await record_turn_test_runs(db, run, [_run_of({NEW[0]: "passed"})], node_id="contract")
    await db.commit()
    stale = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                              json={"action": "confirm", "payload_hash": stale_hash})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "payload_changed"
    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    assert any(f"{NEW[0]} is marked new but already passes" in item for item in view["waiting"]["payload"]["blockers"])
    refused = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                json={"action": "confirm", "payload_hash": view["waiting"]["payload_hash"]})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "nothing_to_confirm"


def test_c_reproduction_is_new_and_the_rest_of_the_suite_is_regression():
    reproduction = "tests/test_totals.py::test_half_up"
    check = [{"type": "reproduces", "params": {"regression": "suite"}, "blocking": True, "description": "Repro"}]
    run = _run_of({reproduction: "failed", "tests/test_fees.py::test_fee": "passed"})
    evidence = TurnEvidence(test_runs=[run], confirmed_tests=[reproduction],
                            confirmed_test_roles={reproduction: "new"}, symptom="assert")
    assert evaluate_checks(check, evidence)[0].outcome == "passed"
    broken = _run_of({reproduction: "failed", "tests/test_fees.py::test_fee": "failed"})
    [result] = evaluate_checks(check, _with_runs(evidence, [broken]))
    assert result.outcome == "failed" and "regression tests fail: tests/test_fees.py::test_fee" in result.detail
    reproduction_only = [{**check[0], "params": {}}]  # without ``regression: suite`` only the reproduction is judged
    assert evaluate_checks(reproduction_only, _with_runs(evidence, [broken]))[0].outcome == "passed"


def _with_runs(evidence: TurnEvidence, runs: list[dict]) -> TurnEvidence:
    from dataclasses import replace

    return replace(evidence, test_runs=runs)


async def _tests_first_run(db, environment: dict | None):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False, tools=[
        "read_workspace_file", "write_workspace_file", "edit_workspace_file", "run_test_suite"]))
    if environment is not None:
        run.context = {**run.context, "workspace_preparation": {"state": "ready", "runtime": "device",
                                                                "spec": {"environment": environment}}}
        await db.flush()
    from tests.workflow_run_octryx_support import STRICT, set_tool_defaults

    await set_tool_defaults(db, workspace_id, **STRICT)  # these tests judge the strict shell

    async def bash(command: str) -> dict:
        return await _decide(db, gateway, key, workspace_id, _hook("Bash", command=command))

    return bash


DECLARED = {"source": "declared", "test": DECLARED_TEST, "lint": "flake8 .", "setup": [], "path": [".venv/bin"]}


@pytest.mark.asyncio
async def test_the_declared_test_command_runs_verbatim_and_a_modified_one_stays_denied(db):
    bash = await _tests_first_run(db, DECLARED)
    assert (await bash(DECLARED_TEST))["decision"] == "allow"
    assert (await bash("flake8 ."))["decision"] == "allow"  # the declared lint command
    for modified in (DECLARED_TEST.replace("report.xml", "other.xml"), DECLARED_TEST + " -p evil",
                     "python -m pytest -v tests/ --junitxml=/tmp/report.xml", DECLARED_TEST + " > out.txt",
                     DECLARED_TEST + " && rm -rf src", "flake8 . --output-file=x"):
        assert (await bash(modified))["reason"] == "outside_phase_tools", modified
    assert (await bash("python -m pytest -v tests/"))["decision"] == "allow"  # the strict allow-list still applies
    assert (await bash(f"cd {ROOT} && git push"))["reason"] == "push_by_platform"


@pytest.mark.asyncio
async def test_only_a_person_s_declaration_is_allowed_verbatim(db):
    proposed = await _tests_first_run(db, {**DECLARED, "source": "ci_derived"})  # a CI-derived proposal
    assert (await proposed(DECLARED_TEST))["reason"] == "outside_phase_tools"
    unprepared = await _tests_first_run(db, None)
    assert (await unprepared(DECLARED_TEST))["reason"] == "outside_phase_tools"


@pytest.mark.asyncio
async def test_a_phase_that_runs_no_tests_gets_no_declared_command(db):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False, tools=[
        "read_workspace_file", "edit_workspace_file"]))
    run.context = {**run.context, "workspace_preparation": {"state": "ready", "spec": {"environment": DECLARED}}}
    from tests.workflow_run_octryx_support import STRICT, set_tool_defaults

    await set_tool_defaults(db, workspace_id, **STRICT)
    decided = await _decide(db, gateway, key, workspace_id, _hook("Bash", command=DECLARED_TEST))
    assert decided["reason"] == "outside_phase_tools"


JUNIT = ('<?xml version="1.0"?><testsuites><testsuite name="pytest">'
         '<testcase classname="tests.test_textkit" name="test_slugify_lowercases"><failure message="assert x"/>'
         '</testcase><testcase classname="tests.test_textkit" name="test_normalize_whitespace_empty"/>'
         '</testsuite></testsuites>')


def test_the_declared_command_s_junit_report_is_the_preferred_evidence():
    from app.services.agent_gateway.tool_execution import test_report
    from app.services.workflow_runs.gateway_tests import bash_test_results

    hook = {"tool_name": "Bash", "workflow_run_facts": {"test_report": {"format": "junit", "path": "r.xml",
                                                                        "junit_xml": JUNIT}}}
    stored = test_report("Bash", hook)
    assert stored == {"format": "junit", "path": "r.xml", "junit_xml": JUNIT}
    assert test_report("Read", hook) is None and test_report("Bash", {"tool_name": "Bash"}) is None
    excerpt = "tests/test_textkit.py::test_slugify_lowercases PASSED"  # the (truncated) output says otherwise
    parsed, files = bash_test_results({"test_report": {**stored, "files": [FILE]}}, excerpt)
    # The report decides; its classnames name a module, keyed canonically once the file is known (no hint here:
    # the launcher's files travel separately and the run resolves them when it records the run).
    assert parsed.results == {} and files == [FILE]
    assert {item["raw"]: item["outcome"] for item in parsed.unresolved} == {
        "tests.test_textkit.test_slugify_lowercases": "failed",
        "tests.test_textkit.test_normalize_whitespace_empty": "passed"}
    from app.services.workflow_checks.test_ids import Resolver
    from app.services.workflow_runs.test_resolution import resolve_entry

    entry = resolve_entry({"results": {}, "unresolved": parsed.unresolved, "files": files}, Resolver())
    assert entry["results"][f"{FILE}::test_slugify_lowercases"]["outcome"] == "failed"
    assert entry["results"][f"{FILE}::test_normalize_whitespace_empty"]["outcome"] == "passed"
    assert "unresolved" not in entry
    printed, _ = bash_test_results({}, excerpt)
    assert printed.results == {f"{FILE}::test_slugify_lowercases": {"outcome": "passed", "message": ""}}


@pytest.mark.asyncio
async def test_the_gateway_stores_the_attached_report_on_the_bash_row(db):
    from sqlalchemy import select

    from app.models import ToolCall
    from app.services.agent_gateway.tool_execution import record_tool_execution

    run, gateway, _key, _workspace_id = await _bound_run(db)
    hook = {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_use_id": "toolu_junit1",
            "workflow_run_facts": {"test_report": {"format": "junit", "path": "test-reports/report.xml",
                                                   "junit_xml": JUNIT}}}
    await record_tool_execution(db, session=gateway, hook_input=hook)
    row = (await db.execute(select(ToolCall).where(ToolCall.request_id == "toolu_junit1"))).scalar_one()
    assert row.parameters["test_report"]["junit_xml"] == JUNIT


def test_b_asks_for_regression_and_c_counts_a_changed_existing_test_red_on_base():
    seeds = {seed["key"]: seed for seed in seed_definitions()}
    b_nodes = {node["id"]: node for node in seeds["feature-delivery-tdd"]["definition"]["nodes"]}
    assert "regression" in b_nodes["clarify"]["config"]["workflow_contract"]["when_to_use"]
    c_nodes = {node["id"]: node for node in seeds["bug-fix-reproduction"]["definition"]["nodes"]}
    # A changed existing test counts when it fails on the base commit.
    assert c_nodes["reproduces"]["config"]["checks"][0]["params"] == {"regression": "suite",
                                                                       "existing_tests": "red_on_base"}


@pytest.mark.asyncio
async def test_a_device_turn_with_the_declared_report_records_the_live_red(db):
    """The run's test history takes the report's per-test results, not the excerpt's."""
    from app.models import ToolCall
    from app.services.workflow_runs.octryx.stop_evidence import phase_evidence

    row = ToolCall(id="r1", session_id="s", tool_name="Bash", status="error", request_id="toolu_x",
                   parameters={"command": DECLARED_TEST, "test_report": {"format": "junit", "junit_xml": JUNIT}},
                   result={"is_error": True, "excerpt": "Exit code 1\n2 failed"})
    evidence = phase_evidence([row], since=None, test_prefixes=(("python", "-m", "pytest"),))
    [unresolved, _passing] = evidence.test_runs[0]["unresolved"]
    assert (unresolved["classname"], unresolved["name"], unresolved["outcome"]) == (
        "tests.test_textkit", "test_slugify_lowercases", "failed")  # keyed when the run records it


@pytest.mark.asyncio
async def test_submitted_test_ids_are_stored_canonical_and_a_bare_name_is_refused(db):
    item = await _item(db)
    _admin, run, _session = await _start(db, contract_definition(), work_item_id=item.id)
    spelled = [{"id": f"./{NEW[0]}", "role": "new"}, {"id": NEW[1].replace("/", "\\"), "role": "new"},
               {"id": "tests.test_textkit.test_slugify_empty_string", "role": "new"}]
    recorded = await submit_output(db, run, "submit_test_contract", {"criteria": [{**LIVE_CRITERIA[0],
                                                                                    "tests": spelled}]})
    assert recorded["state"] == "recorded", recorded
    criterion = run.context["outputs"]["test_contract"]["record"]["criteria"][0]
    canonical = [NEW[0], NEW[1], f"{FILE}::test_slugify_empty_string"]  # the dotted one resolved by its sibling
    assert criterion["tests"] == canonical and criterion["test_roles"] == dict.fromkeys(canonical, "new")
    bare = await submit_output(db, run, "submit_test_contract", {"criteria": [
        {**LIVE_CRITERIA[0], "tests": [{"id": "test_slugify_lowercases", "role": "new"}]}]})
    assert bare["state"] == "refused" and "test_slugify_lowercases is not a test id: name its file" in bare["message"]


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
