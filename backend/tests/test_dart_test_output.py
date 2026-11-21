"""Flutter / Dart test runs as evidence: a reproduce phase's Dart test is accepted by submit_reproduction and
its run recorded. Fixtures: real ``flutter test`` output, paths anonymized."""

from pathlib import Path

from app.services.workflow_checks.test_command_outcome import RAN, classify
from app.services.workflow_checks.test_ids import Resolver, selects
from app.services.workflow_checks.test_output import FAILED, PASSED, SKIPPED, parse
from app.services.workflow_checks.test_results import DEFAULT_TEST_PREFIXES

FIXTURES = Path(__file__).parent / "fixtures" / "dart"
FILE = "test/features/a_test.dart"


def _results(name: str):
    return parse((FIXTURES / name).read_text())


def test_a_single_file_run_keys_every_test_by_its_file_and_full_name():
    parsed = _results("single_file.txt")
    assert parsed.format == "dart" and parsed.problems == []
    outcomes = {key: value["outcome"] for key, value in parsed.results.items()}
    assert outcomes == {f"{FILE}::Grind OCX-72_grind_starts_at_15": FAILED, f"{FILE}::Grind keeps value": PASSED,
                        f"{FILE}::top level ok": PASSED, f"{FILE}::skipped one": SKIPPED}
    assert "Expected: '15.0'" in parsed.results[f"{FILE}::Grind OCX-72_grind_starts_at_15"]["message"]


def test_a_sequential_run_of_several_files_is_attributed_per_test():
    parsed = _results("two_files_j1.txt")
    assert parsed.problems == []
    assert parsed.results["test/b_test.dart::b passes"]["outcome"] == PASSED
    assert parsed.results[f"{FILE}::Grind OCX-72_grind_starts_at_15"]["outcome"] == FAILED


def test_a_concurrent_run_keeps_only_its_failures_and_says_why():
    parsed = _results("two_files.txt")
    assert {key: value["outcome"] for key, value in parsed.results.items()} == {
        f"{FILE}::Grind OCX-72_grind_starts_at_15": FAILED}
    assert parsed.problems and "JSON reporter" in parsed.problems[0]


def test_a_dart_test_id_is_canonical_and_named_without_its_groups():
    assert Resolver().selector(f"{FILE}::OCX-72_grind_starts_at_15") == (f"{FILE}::OCX-72_grind_starts_at_15", "")
    assert selects(f"{FILE}::OCX-72_grind_starts_at_15", f"{FILE}::Grind OCX-72_grind_starts_at_15")
    assert selects(FILE, f"{FILE}::Grind OCX-72_grind_starts_at_15")
    assert not selects(f"{FILE}::starts_at_15", f"{FILE}::Grind OCX-72_grind_starts_at_15")
    assert not selects("test/x_test.py::b", "test/x_test.py::a b")  # the group rule is Dart's only


def test_flutter_and_dart_test_are_test_commands_that_ran():
    assert ("flutter", "test") in DEFAULT_TEST_PREFIXES and ("dart", "test") in DEFAULT_TEST_PREFIXES
    assert classify({"excerpt": (FIXTURES / "single_file.txt").read_text()}, command="flutter test").kind == RAN


def test_a_tailed_single_file_run_takes_its_file_from_the_command():
    """``flutter test <file> 2>&1 | tail -30`` loses the loading line; the run must still be recorded and the red
    run must not count as green."""
    from app.services.workflow_runs.gateway_tests import bash_test_results

    tail = "\n".join((FIXTURES / "single_file.txt").read_text().splitlines()[1:])
    parsed, _files = bash_test_results({"command": f"cd app && flutter test {FILE} 2>&1 | tail -30"}, tail)
    assert parsed.results[f"{FILE}::Grind OCX-72_grind_starts_at_15"]["outcome"] == FAILED
    assert parsed.results[f"{FILE}::Grind keeps value"]["outcome"] == PASSED


def test_a_run_cut_to_its_failing_block_records_the_failing_test():
    """``flutter test 2>&1 | tail -n 5`` keeps only the closing "Failing tests:" block."""
    tail = (f"00:23 +393 -1: /w/app/test/features/equipment/equipment_screen_test.dart: delete buttons\n"
            f"00:23 +394 -1: Some tests failed.\n\nFailing tests:\n  /w/app/{FILE}: OCX-72_grind_starts_at_15\n")
    parsed = parse(tail)
    assert parsed.results[f"{FILE}::OCX-72_grind_starts_at_15"]["outcome"] == FAILED


def test_a_prose_symptom_matches_its_assertion_by_its_quoted_values():
    from app.services.workflow_checks.library import shows_symptom

    symptom = ("The grind field starts at the scale minimum instead of 15. Assertion: expected '15.0', "
               "actual '1.0'.")
    assert shows_symptom(symptom.lower(), "Expected: '15.0' Actual: '1.0' Which: is different.")
    assert not shows_symptom(symptom.lower(), "Expected: '15.0' Actual: '0.0'")
    assert shows_symptom("assert 2 == 3", "AssertionError: assert 2 == 3")  # the old exact form still holds
    assert not shows_symptom("the totals round down", "Expected: '3' Actual: '2'")


def test_a_concurrent_run_that_ends_all_green_passes_every_test_it_named():
    """The whole suite runs concurrently and ends "All tests passed!"; the confirmed test must not count as missing
    from the last run."""
    parsed = _results("two_files_green.txt")
    assert parsed.problems == []
    assert {key: value["outcome"] for key, value in parsed.results.items()} == {
        f"{FILE}::Grind OCX-72_grind_starts_at_15": PASSED, f"{FILE}::Grind keeps value": PASSED,
        f"{FILE}::top level ok": PASSED, f"{FILE}::skipped one": PASSED, "test/b_test.dart::b passes": PASSED}


def test_a_whole_suite_that_passed_counts_every_confirmed_test_even_unnamed():
    """`flutter test | tail -3` names two tests and ends "+395: All tests passed!"; the confirmed test must not be
    "missing from the last test run"."""
    from app.services.workflow_checks.test_results import all_green, intact
    from app.services.workflow_runs.gateway_tests import bash_test_results, gateway_test_run

    tail = ("00:19 +393: /w/app/test/features/equipment/equipment_screen_test.dart: AC10 deleted grinder\n"
            "00:19 +394: /w/app/test/features/equipment/equipment_screen_test.dart: delete buttons\n"
            "00:19 +395: All tests passed!\n")
    confirmed = ["test/app/persistence_reload_test.dart::saved grinder survives reload"]
    parsed, files = bash_test_results({"command": "flutter test | tail -3"}, tail)
    run = gateway_test_run(parsed, files, green=True)
    assert run["suite_passed"] == 395
    assert all_green(run, confirmed) == (True, "") and intact(run, confirmed) == (True, "")
    # Only the whole suite stands for every test: a run of one file does not.
    part, _ = bash_test_results({"command": "flutter test test/features/equipment | tail -3"}, tail)
    assert not part.suite_passed
    assert all_green(gateway_test_run(part, [], green=True), confirmed)[0] is False


def test_a_file_that_does_not_compile_is_a_collection_error_of_that_file():
    """Finding 7 (top-10 #9): "loading <file> [E]" was recorded as a test named "loading …"; the pattern is stack
    data (engineering_knowledge/stacks.json, flutter test_output.collection_error)."""
    from app.services.workflow_checks.test_output import ERROR, SCOPE_COLLECTION

    for line in ("00:02 +0 -1: loading /work/app/test/features/a_test.dart [E]",
                 "00:02 +0 -1: /work/app/test/features/a_test.dart: loading /work/app/test/features/a_test.dart [E]"):
        text = "\n".join(["00:00 +0: loading /work/app/test/features/a_test.dart", line,
                          "  Error: Undefined name 'grinder'.", "00:02 +0 -1: Some tests failed."])
        parsed = parse(text)
        assert parsed.results == {FILE: {"outcome": ERROR, "message": "Error: Undefined name 'grinder'.",
                                         "scope": SCOPE_COLLECTION}}, line
    from app.services.workflow_checks import test_output

    assert "[E]$" not in Path(test_output.__file__).read_text(encoding="utf-8")


def test_the_json_reporter_attributes_every_test_of_concurrent_files():
    """evidence_unresolved with concurrent `flutter test`: the JSON reporter names each test's
    suite, so every result is attributed even when files interleave (real output of three files, one not compiling)."""
    from app.services.workflow_checks.test_output import ERROR, SCOPE_COLLECTION

    parsed = _results("concurrent_json.txt")
    assert parsed.problems == []
    outcomes = {key: value["outcome"] for key, value in parsed.results.items()}
    assert outcomes == {"test/b_test.dart::b passes": PASSED, "test/b_test.dart::b also passes": PASSED,
                        "test/a_test.dart::Grind keeps value": PASSED, "test/a_test.dart::Grind starts at 15": FAILED,
                        "test/a_test.dart::skipped one": SKIPPED, "test/c_test.dart": ERROR}
    assert parsed.results["test/c_test.dart"]["scope"] == SCOPE_COLLECTION
    assert "Undefined name 'grinder'" in parsed.results["test/c_test.dart"]["message"]
    assert "Expected: <15>" in parsed.results["test/a_test.dart::Grind starts at 15"]["message"]
