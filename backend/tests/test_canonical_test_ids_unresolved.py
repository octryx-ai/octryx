"""Collection errors, unittest output, ambiguous or unknown modules, submitted selectors and CI cases from every provider resolve to canonical test ids or stay explicitly unresolved."""

from __future__ import annotations

from app.services.workflow_checks.test_command_outcome import NOT_RUN, RAN, classify
from app.services.workflow_checks.test_ids import Resolver, normalize, selects
from app.services.workflow_checks.test_output import parse
from app.services.workflow_checks.test_results import evidence_unresolved
from app.services.workflow_checks.test_results import test_run_from_tool as run_from_tool
from app.services.workflow_runs.gateway_tests import bash_test_results
from app.services.workflow_runs.test_resolution import resolve_entry
from tests.canonical_test_ids_matrix_support import (  # noqa: F401
    GREEN,
    NEW,
    RED,
    _chat_run,
    _decide,
    _device_run,
    _ids,
    _pytest,
    _repo,
    _run,
    textkit,
)

REPRODUCES = [{"type": "reproduces", "params": {"regression": "suite"}, "blocking": True, "description": "Repro"}]


# --- collection errors ----------------------------------------------------------------------------------------------

BROKEN = "from textkit import missing_function\n\n\ndef test_uses_missing():\n    assert missing_function() == 1\n"


# --- unittest -------------------------------------------------------------------------------------------------------

UNITTEST = '''import unittest


class TestTotals(unittest.TestCase):
    def test_rounds_half_up(self):
        """Half rounds up (a docstring line sits between the header and the traceback)."""
        self.assertEqual(round(2.5 + 0.5), 4)

    def test_zero(self):
        """Zero stays zero."""
        self.assertEqual(0, 0)

    @unittest.skip("later")
    def test_later(self):
        pass
'''


def test_a_collection_error_ran_no_test_and_covers_the_tests_of_its_file(textkit):  # noqa: F811
    (textkit / "tests" / "test_broken.py").write_text(BROKEN)
    done, xml = _pytest(textkit, "-v", "tests/", junit=True)
    parsed, _files = bash_test_results({"test_report": {"junit_xml": xml}}, done.stdout)
    assert parsed.executed() == 0  # pytest stopped at the collection error: no test ran
    assert classify({"excerpt": done.stdout, "exit_code": done.returncode}, command="pytest",
                    parsed_results=parsed.executed()).kind == NOT_RUN
    # Collected anyway (--continue-on-collection-errors): the broken file's tests error before their assertions.
    done, xml = _pytest(textkit, "-v", "--continue-on-collection-errors", "tests/", junit=True)
    run = _device_run(done, xml, files=["tests/test_broken.py", *NEW])
    assert run["results"]["tests/test_broken.py"] == {"outcome": "error", "message": "collection failure",
                                                      "scope": "collection"}
    assert classify({"excerpt": done.stdout, "exit_code": done.returncode}, command="pytest",
                    parsed_results=4).kind == RAN
    confirmed = ["tests/test_broken.py::test_uses_missing"]
    result = _decide(RED, run, confirmed)
    assert result.outcome == "failed" and not result.unresolved and "errors before its assertions" in result.detail
    printed = _chat_run(done, None)  # the -v/-rA lines name the file the same way
    assert printed["results"]["tests/test_broken.py"]["scope"] == "collection"


def test_unittest_output_maps_to_node_ids_with_the_repository_tree(tmp_path):
    root = _repo(tmp_path, {"tests/__init__.py": "", "tests/test_totals.py": UNITTEST})
    done = _run(root, "-m", "unittest", "-v")
    assert "Ran 3 tests" in done.stderr
    run = _chat_run(done, root)
    assert _ids(run) == {"tests/test_totals.py::TestTotals::test_rounds_half_up": "failed",
                         "tests/test_totals.py::TestTotals::test_zero": "passed",
                         "tests/test_totals.py::TestTotals::test_later": "skipped"}, (done.stderr, run)
    assert "AssertionError: 3 != 4" in run["results"]["tests/test_totals.py::TestTotals::test_rounds_half_up"][
        "message"]
    confirmed = {"tests/test_totals.py::TestTotals::test_rounds_half_up": "new",
                 "tests/test_totals.py::TestTotals::test_zero": "regression"}
    assert _decide(RED, run, list(confirmed), confirmed).outcome == "passed"
    # The same tests under pytest have the same ids: one canonical id for both runners.
    pytest_done, xml = _pytest(root, "-v", "tests", junit=True)
    assert set(_ids(_device_run(pytest_done, xml, files=list(confirmed)))) == set(_ids(run))


def test_a_unittest_module_that_fails_to_import_is_a_collection_error(tmp_path):
    root = _repo(tmp_path, {"tests/__init__.py": "", "tests/test_totals.py": UNITTEST,
                            "tests/test_broken.py": "import does_not_exist\n"})
    done = _run(root, "-m", "unittest", "-v")
    run = _chat_run(done, root)
    assert run["results"]["tests/test_broken.py"]["outcome"] == "error", (done.stderr, run)
    assert run["results"]["tests/test_broken.py"]["scope"] == "collection"


# --- ambiguity and unknown files: explicit, never matched -----------------------------------------------------------


def test_an_ambiguous_or_unknown_module_stays_unresolved_and_pauses_instead_of_failing(tmp_path):
    root = _repo(tmp_path, {"tests/test_a.py": "class TestX:\n    def test_y(self):\n        assert False\n",
                            "tests/test_a/TestX.py": "", "tests/test_b.py": "def test_ok():\n    assert True\n"})
    done, xml = _pytest(root, "-v", "tests/test_a.py", "tests/test_b.py", junit=True)
    entry = run_from_tool("run_test_suite", {"stdout": xml, "exit_code": done.returncode}, source="chat")
    run = resolve_entry(entry, Resolver(root=root))
    [ambiguous] = run["unresolved"]
    assert ambiguous["raw"] == "tests.test_a.TestX.test_y" and "ambiguous" in ambiguous["reason"]
    assert _ids(run) == {"tests/test_b.py::test_ok": "passed"}
    confirmed = ["tests/test_a.py::TestX::test_y"]
    reasons = evidence_unresolved(run, confirmed)
    assert reasons and "tests/test_a.py::TestX::test_y" in reasons[0]
    result = _decide(RED, run, confirmed)
    assert result.outcome == "failed" and result.unresolved  # the platform's problem: the run pauses
    # C: a failing result with an unknown id cannot be told regression or reproduction.
    repro = _decide(REPRODUCES, run, ["tests/test_b.py::test_ok"], {"tests/test_b.py::test_ok": "new"})
    assert repro.unresolved and "failing tests with an unresolved id" in repro.detail
    assert _decide(GREEN, run, ["tests/test_b.py::test_ok"]).outcome == "failed"  # a failing test fails green


def test_submitted_ids_are_canonical_selectors_or_refused():
    resolver = Resolver(["tests/test_textkit.py"])
    assert resolver.selector("./tests\\test_textkit.py::test_x") == ("tests/test_textkit.py::test_x", "")
    assert resolver.selector("tests.test_textkit.test_x") == ("tests/test_textkit.py::test_x", "")
    assert resolver.selector("tests.test_textkit") == ("tests/test_textkit.py", "")
    assert resolver.selector("tests/") == ("tests/", "")
    for refused in ("test_x", "/abs/tests/test_x.py::t", "../tests/test_x.py::t", "tests.unknown.test_x"):
        test_id, why = resolver.selector(refused)
        assert test_id is None and "not a test id" in why, refused
    assert normalize("tests/test_x.py::()::TestA::test") == "tests/test_x.py::TestA::test"
    assert selects("tests/test_x.py::test_p", "tests/test_x.py::test_p[1]")
    assert not selects("tests/test_x.py::test_p", "tests/test_x.py::test_p2")  # no prefix confusion
    assert not selects("tests/test_x.py::test_p[1]", "tests/test_x.py::test_p[10]")
    assert not selects("tests/test_x", "tests/test_x.py::test_p")
    assert selects("tests/", "tests/unit/test_x.py::test_p")


def test_ci_cases_from_every_provider_go_through_the_same_converter(tmp_path):
    from app.services.workflow_runs.platform.ci_tests import bitbucket_tests, from_cases, from_junit, jenkins_report

    hints = Resolver(["tests/test_totals.py"])
    gitlab = from_cases([{"classname": "tests.test_totals", "name": "test_half_up", "file": "tests/test_totals.py",
                          "status": "failed", "message": "assert 2 == 3"},
                         {"classname": "tests.test_totals", "name": "test_zero", "file": "", "status": "success"}])
    assert _ids(resolve_entry({"results": {}, **gitlab.fields()}, hints)) == {
        "tests/test_totals.py::test_half_up": "failed", "tests/test_totals.py::test_zero": "passed"}
    bitbucket = bitbucket_tests([{"state": "FAILED", "test_cases": [
        {"classname": "tests.test_totals", "name": "test_half_up", "status": "FAILED"}]}])
    assert _ids(resolve_entry({"results": {}, **bitbucket.fields()}, hints)) == {
        "tests/test_totals.py::test_half_up": "failed"}
    jenkins = jenkins_report({"suites": [{"cases": [{"className": "tests.test_totals", "name": "test_zero",
                                                     "status": "FIXED"}]}]})
    assert _ids(resolve_entry({"results": {}, **jenkins.fields()}, hints)) == {"tests/test_totals.py::test_zero": "passed"}
    xml = '<testsuite><testcase classname="tests.test_totals" name="test_zero" file="tests/test_totals.py"/></testsuite>'
    assert _ids({"results": from_junit([{"junit_xml": xml}]).results}) == {"tests/test_totals.py::test_zero": "passed"}
    assert from_junit([{"path": "r.xml", "junit_xml": "<testsuite><testcase"}]).problems  # unreadable: a problem


def test_the_parsed_ids_of_a_report_and_its_printed_lines_agree(textkit):  # noqa: F811
    done, xml = _pytest(textkit, "-v", "-rA", "tests/", junit=True)
    assert _ids(_device_run(done, xml, files=NEW)) == _ids(_chat_run(done, None))
    assert parse(xml, Resolver(root=textkit)).results.keys() == parse(done.stdout).results.keys()
