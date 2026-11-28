"""A changed existing test is the reproduction when it fails on the base commit and the gate says
``existing_tests: "red_on_base"``; without that parameter the gate is unchanged."""

from __future__ import annotations

import json

from app.services.workflow_checks.library import TurnEvidence, evaluate_checks
from app.services.workflow_runs.seeding import SEEDS_PATH

TEST = "test/features/brews/brew_form_test.dart::grind stepper moves by one scale step and stops at the ends"
RUN = {"source": "device", "results": {TEST: {"outcome": "failed", "message": "Expected: '15.0' Actual: '1.0'"}}}


def _verdict(params: dict, proof: dict | None):
    evidence = TurnEvidence(tools=[], test_runs=[RUN], confirmed_tests=[TEST],
                            confirmed_test_roles={TEST: "regression"}, red_on_base=proof)
    [result] = evaluate_checks([{"type": "reproduces", "params": params, "blocking": True}], evidence)
    return result.outcome, result.detail


def test_a_changed_existing_test_red_on_base_reproduces():
    proven = {"state": "proven", "tests": {TEST: "failed"}, "unnamed_changes": []}
    assert _verdict({"existing_tests": "red_on_base"}, proven)[0] == "passed"
    assert _verdict({"existing_tests": "red_on_base"}, {**proven, "tests": {TEST: "error"}})[0] == "passed"


def test_without_the_proof_or_the_parameter_it_does_not_and_says_why():
    outcome, why = _verdict({"existing_tests": "red_on_base"}, None)
    assert outcome == "failed" and "fails on the base commit" in why and "not run on base" in why
    outcome, why = _verdict({"existing_tests": "red_on_base"}, {"tests": {TEST: "passed"}, "reason": "green on base"})
    assert outcome == "failed" and "passed on base" in why and "green on base" in why
    assert _verdict({}, {"tests": {TEST: "failed"}})[1].startswith("no new confirmed test")


def test_a_changed_test_file_the_reproduction_does_not_name_is_refused():
    proof = {"tests": {TEST: "failed"}, "unnamed_changes": ["test/other_test.dart"]}
    outcome, why = _verdict({"existing_tests": "red_on_base"}, proof)
    assert outcome == "failed" and "test/other_test.dart changed" in why


def test_the_bug_workflow_takes_changed_tests_proven_red_on_base():
    seed = next(item for item in json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
                if item["key"] == "bug-fix-reproduction")
    [check] = [check for node in seed["definition"]["nodes"] for check in (node.get("config") or {}).get("checks") or []
               if check.get("type") == "reproduces"]
    assert check["params"] == {"regression": "suite", "existing_tests": "red_on_base"}
