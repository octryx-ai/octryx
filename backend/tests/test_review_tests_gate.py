"""A review of a phase that may not change tests never blocks on a test request (the fix phase's Write of the
requested test is refused, so the review loop would have no legal move)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.workflow_runs.review import tests_gate as gate
from app.services.workflow_runs.review.answer_checks import _reviewed_phase_protects_tests
from app.services.workflow_runs.review.convergence import Settled
from app.services.workflow_runs.review.verdict import Finding, Verdict

OE72 = Finding("medium", "coffee/flutter/claude/lib/features/equipment/domain/grinder_scale.dart", 12,
               "Add a unit test in test/features/equipment/ that asserts GrinderScale.initial returns 15", "F3")
SCOPE = Finding("medium", "coffee/flutter/claude/.octryx/environment.json", 4, "Remove the venv entries", "F1")


def test_a_test_request_becomes_a_low_follow_up_and_the_rest_still_decides():
    only = gate.tests_gate(Settled(Verdict("changes", "", (OE72,))))
    (finding,) = only.verdict.findings
    assert (finding.severity, finding.id) == ("low", "F3") and finding.fix.startswith(gate.FOLLOW_UP_MARK)
    assert only.verdict.verdict == "pass"
    mixed = gate.tests_gate(Settled(Verdict("changes", "", (SCOPE, OE72))))
    assert [item.severity for item in mixed.verdict.findings] == ["medium", "low"]
    assert mixed.verdict.verdict == "changes"  # F1 still blocks
    on_test_file = Finding("high", "coffee/flutter/claude/test/app/x_test.dart", 3, "assert the reload", "F2")
    assert gate.tests_gate(Settled(Verdict("changes", "", (on_test_file,)))).verdict.verdict == "pass"
    untouched = Settled(Verdict("changes", "", (SCOPE,)))
    assert gate.tests_gate(untouched) is untouched


def test_only_a_review_of_a_test_protected_phase_is_gated():
    protected = {"workflow_contract": {"path_rules": {"protect_confirmed_tests": True}}}
    graph = SimpleNamespace(nodes={"fix": SimpleNamespace(config=protected), "build": SimpleNamespace(config={})})
    run = SimpleNamespace(context={"last_phase": "fix"})
    assert _reviewed_phase_protects_tests(graph, run, {}) is True
    assert _reviewed_phase_protects_tests(graph, run, {"phase": "build"}) is False
    assert _reviewed_phase_protects_tests(graph, SimpleNamespace(context={}), {}) is False
