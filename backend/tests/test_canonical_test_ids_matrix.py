"""The canonical test id, proven on real test runs."""

from __future__ import annotations

import pytest

from app.services.workflow_checks.test_ids import Resolver
from app.services.workflow_checks.test_results import test_run_from_tool as run_from_tool
from app.services.workflow_runs.test_resolution import resolve_entry
from tests.canonical_test_ids_matrix_support import (  # noqa: F401
    GREEN,
    NEW,
    RED,
    TEXTKIT,
    _chat_run,
    _decide,
    _device_run,
    _ids,
    _pytest,
    _repo,
    textkit,
)

REGRESSION = ["tests/test_textkit.py::test_normalize_whitespace_collapses_and_trims",
              "tests/test_textkit.py::test_normalize_whitespace_empty"]


ROLES = {**dict.fromkeys(NEW, "new"), **dict.fromkeys(REGRESSION, "regression")}


EXPECTED_RED = {**dict.fromkeys(NEW, "failed"), **dict.fromkeys(REGRESSION, "passed")}


STRUCTURE = {
    "tests/unit/sub/test_deep.py": '''import pytest


class TestOuter:
    class TestInner:
        def test_nested(self):
            assert 1 == 2

    def test_method(self):
        assert True


@pytest.mark.parametrize("value", [1, 2])
def test_param(value):
    assert value == 1


@pytest.mark.parametrize("text", [pytest.param("x", id="a.b c")])
def test_odd_id(text):
    assert text == "x"
''',
}


DEEP = "tests/unit/sub/test_deep.py"


EXPECTED_DEEP = {f"{DEEP}::TestOuter::TestInner::test_nested": "failed", f"{DEEP}::TestOuter::test_method": "passed",
                 f"{DEEP}::test_param[1]": "passed", f"{DEEP}::test_param[2]": "failed",
                 f"{DEEP}::test_odd_id[a.b c]": "passed"}


def test_the_live_declared_command_with_junit_keys_canonically_and_passes_the_red_gate(textkit):  # noqa: F811
    done, xml = _pytest(textkit, "-v", "tests/", junit=True)
    assert done.returncode == 1 and xml and 'classname="tests.test_textkit"' in xml
    # The device: the server has only the confirmed tests as hints (no tree) — enough to key the module.
    run = _device_run(done, xml, files=[*NEW, *REGRESSION])
    assert _ids(run) == EXPECTED_RED and "unresolved" not in run
    assert _decide(RED, run, NEW + REGRESSION, ROLES).outcome == "passed"
    # The launcher's own files (what it attaches next to the report) key it without any confirmed test yet.
    clarify = _device_run(done, xml, report_files=["tests/test_textkit.py"])
    assert _ids(clarify) == EXPECTED_RED
    assert _ids(_chat_run(done, textkit)) == EXPECTED_RED
    # Without any file the report is unresolved, explicitly.
    blind = _device_run(done, xml)
    assert blind["results"] == {} and len(blind["unresolved"]) == 4
    result = _decide(RED, blind, NEW + REGRESSION, ROLES)
    assert result.outcome == "failed" and result.unresolved and "evidence unresolved" in result.detail


@pytest.mark.parametrize("flags", [("-v",), ("-rA",), ("-v", "-rA"), ("-q", "-rA")])
def test_printed_output_without_a_report_is_already_canonical(textkit, flags):  # noqa: F811
    done, _ = _pytest(textkit, *flags, "tests/")
    run = _chat_run(done, None)  # no tree, no hint: node ids need none
    assert _ids(run) == EXPECTED_RED
    assert _decide(RED, run, NEW + REGRESSION, ROLES).outcome == "passed"
    if "-rA" in flags:  # the short summary's message (pytest cuts it at the terminal width; JUnit keeps it whole)
        assert run["results"][NEW[0]]["message"].startswith("AssertionError")


def test_quiet_output_that_lists_only_failures_is_an_evidence_problem_not_the_agents(textkit):  # noqa: F811
    done, _ = _pytest(textkit, "-q", "tests/")  # pytest -q lists failures only: the regression tests are unseen
    run = _chat_run(done, textkit)
    assert set(run["results"]) == set(NEW) and run["problems"]
    result = _decide(RED, run, NEW + REGRESSION, ROLES)
    assert result.unresolved and "lists 2 of the 4 tests" in result.detail


def test_the_green_gate_after_the_fix_with_the_report(textkit):  # noqa: F811
    (textkit / "textkit.py").write_text(TEXTKIT.replace("return text  # not implemented yet",
                                                        "return re.sub(r'\\s+', '-', text.lower())"))
    done, xml = _pytest(textkit, "-v", "tests/", junit=True)
    assert done.returncode == 0
    run = _device_run(done, xml, files=NEW)
    assert set(_ids(run).values()) == {"passed"} and len(run["results"]) == 4
    assert _decide(GREEN, run, NEW + REGRESSION).outcome == "passed"


@pytest.mark.parametrize("junit", [True, False])
def test_classes_nested_directories_and_parametrize_map_to_node_ids(tmp_path, junit):
    root = _repo(tmp_path, STRUCTURE)
    done, xml = _pytest(root, "-v", "-rA", "tests", junit=junit)
    run = _device_run(done, xml, files=[DEEP]) if junit else _chat_run(done, None)
    assert _ids(run) == EXPECTED_DEEP, run
    assert _decide(RED, run, [f"{DEEP}::TestOuter::TestInner"]).outcome == "passed"
    assert _decide(RED, run, [f"{DEEP}::test_param"]).outcome == "passed"  # one case fails on its assertion
    regression = {f"{DEEP}::TestOuter::test_method": "regression", f"{DEEP}::test_odd_id[a.b c]": "regression",
                  f"{DEEP}::test_param[2]": "new"}
    assert _decide(RED, run, list(regression), regression).outcome == "passed"
    assert _decide(GREEN, run, [f"{DEEP}::test_odd_id"]).outcome == "failed"  # the suite is not green


def test_the_server_tree_resolves_nested_classes_from_a_report_without_hints(tmp_path):
    root = _repo(tmp_path, STRUCTURE)
    done, xml = _pytest(root, "-v", "tests", junit=True)
    entry = run_from_tool("run_test_suite", {"stdout": xml, "exit_code": done.returncode}, source="chat")
    assert entry["results"] == {} and len(entry["unresolved"]) == 5  # chat cannot know the files by itself …
    assert _ids(resolve_entry(entry, Resolver(root=root))) == EXPECTED_DEEP  # … the run's working copy can


def test_k_selection_leaves_the_unselected_tests_unseen_and_that_is_the_agents_run(textkit):  # noqa: F811
    done, xml = _pytest(textkit, "-v", "-k", "slugify", "tests/", junit=True)
    run = _device_run(done, xml, files=NEW)
    assert set(run["results"]) == set(NEW) and "unresolved" not in run
    result = _decide(RED, run, NEW + REGRESSION, ROLES)
    assert result.outcome == "failed" and not result.unresolved and "not seen" in result.detail


def test_xdist_ordering_maps_to_the_same_ids(textkit):  # noqa: F811
    pytest.importorskip("xdist")
    done, _ = _pytest(textkit, "-v", "-n", "2", "tests/")
    assert "[gw" in done.stdout
    run = _chat_run(done, None)
    assert _ids(run) == EXPECTED_RED
    done, xml = _pytest(textkit, "-n", "2", "tests/", junit=True)
    assert _ids(_device_run(done, xml, files=NEW)) == EXPECTED_RED
