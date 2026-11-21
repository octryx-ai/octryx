"""A pipeline report's command results: exit codes, no tests and flaky tests, test runs, the environment file audit."""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRun

TIMING_STEPS = ("tree", "green_before", "setup", "commands", "screenshots", "red_on_base", "code_style", "total")
TAIL_CHARS = 20_000  # the end of a command's output kept on the run (its JUnit report is kept as per-test results)
FLAKY_KEY = "pipeline_flaky"
MAX_FLAKY_IDS = 500  # a guard against a broken report, far above a real suite's flaky tests


def _timings(value: Any) -> dict[str, float]:
    """The device's seconds per step (:data:`TIMING_STEPS`), anything else dropped."""
    if not isinstance(value, dict):
        return {}
    return {step: round(float(value[step]), 1) for step in TIMING_STEPS
            if isinstance(value.get(step), int | float) and not isinstance(value.get(step), bool) and value[step] >= 0}


def _file_audit(pointer: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """The device's account of the environment file, validated again here: ``file_state`` ``ok`` with the
    ``commands`` it declares, else the state and errors the agent gets."""
    from .workspace.spec import FILE_INVALID, FILE_OK, refused_command, validate_environment

    reported = report.get("environment_file") if isinstance(report.get("environment_file"), dict) else {}
    audit: dict[str, Any] = {"source": "environment_file", "file": pointer.get("file"),
                             "app_folder": pointer.get("app_folder"),
                             "sha256": str(reported.get("sha256") or "")[:64] or None}
    setup = [{"command": str(item.get("command") or "")[:300], "exit_code": item.get("exit_code"),
              "output_end": str(item.get("output_tail") or "")[-2000:]}
             for item in reported.get("setup") or [] if isinstance(item, dict)][:10]
    if setup:
        audit["setup"] = setup
    state_ = str(reported.get("state") or "")
    errors = [str(item)[:300] for item in reported.get("errors") or [] if isinstance(item, str)][:20]
    if reported.get("file") != pointer.get("file") or reported.get("app_folder") != pointer.get("app_folder"):
        return {**audit, "file_state": FILE_INVALID, "file_errors": [
            f"the device ran {reported.get('file') or 'no environment file'}, not {pointer.get('file')}"]}
    if state_ != FILE_OK:
        return {**audit, "file_state": state_ or FILE_INVALID, "file_errors": errors}
    environment, again = validate_environment(reported.get("environment"))
    commands = [str((environment or {}).get(key) or "") for key in ("test", "system_test")]
    commands = [command for command in commands if command]
    again += [f"'{command[:80]}' is refused: {why}" for command in [str(item) for item in reported.get(
        "commands") or []] if (why := refused_command(command))]
    if again or not commands or [str(item) for item in reported.get("commands") or []] != commands:
        return {**audit, "file_state": FILE_INVALID,
                "file_errors": again or ["the reported commands are not the file's test and system_test"]}
    return {**audit, "file_state": FILE_OK, "commands": commands}


PYTEST_NO_TESTS = 5  # pytest: "no tests ran"
PYTEST_USAGE = 4  # pytest: usage error, among them "file or directory not found" for a missing test path


def _no_tests(command: str, code: int, output: str) -> bool:
    """A pytest command that collected nothing: exit 5, or exit 4 because its test path does not exist.

    Without this, a story without system tests (no ``tests/system`` yet, exit 4) or without
    unit tests (exit 5) was red, looped three times and paused. Nothing collected is "no tests", not a failure; a task
    whose proof test should have run there stays unproven, so the pipeline is red for that reason alone."""
    if "pytest" not in command:
        return False
    text = output.lower()
    no_tests = "no tests ran" in text or "collected 0 items" in text or not text.strip()
    return (code == PYTEST_NO_TESTS and no_tests) or (code == PYTEST_USAGE and "file or directory not found" in text)


def _green(item: dict[str, Any]) -> bool:
    """The command is green: it passed, it collected nothing, or its re-run passed and every test that flipped is
    flaky for the first time in this run."""
    if item.get("exit_code") == 0 or item.get("no_tests"):
        return True
    rerun = item.get("rerun") or {}
    return rerun.get("exit_code") == 0 and bool(item.get("flaky")) and not item.get("flaky_again")


def _run_part(item: dict[str, Any]) -> dict[str, Any]:
    code = item.get("exit_code")
    return {"exit_code": code if type(code) is int else -1,
            "seconds": item.get("seconds") if isinstance(item.get("seconds"), (int, float)) else None,
            "output_tail": str(item.get("output_tail") or "")[-TAIL_CHARS:],
            "junit_xml": item.get("junit_xml") if isinstance(item.get("junit_xml"), str) else None,
            "junit_files": [str(file) for file in item.get("junit_files") or [] if isinstance(file, str)]}


def _ids(value: Any) -> list[str]:
    return [str(test) for test in value or [] if isinstance(test, str) and test.strip()][:MAX_FLAKY_IDS] if (
        isinstance(value, list)) else []


def _results(report: dict[str, Any], commands: list[str]) -> list[dict[str, Any]]:
    results = []
    for item in report.get("results") or []:
        if not isinstance(item, dict) or str(item.get("command") or "") not in commands:
            continue
        if item.get("skipped"):
            # Fail fast on the device: the system test did not start after a red check. Not a
            # failure of its own, not green either; the agent is told it is still due.
            results.append({"command": str(item["command"]), "exit_code": None, "seconds": None, "output_tail": "",
                            "junit_xml": None, "junit_files": [], "skipped": str(item["skipped"])[:200]})
            continue
        part = _run_part(item)
        result = {"command": str(item["command"]), **part,
                  **({"no_tests": True} if _no_tests(str(item["command"]), part["exit_code"], part["output_tail"])
                     else {}),
                  # The launcher re-reported its green run of this very tree instead of running it again
                  # (``octryx_claude.pipeline.green_before``): on record, never hidden.
                  **({"reused_green_run": item["reused_green_run"]}
                     if isinstance(item.get("reused_green_run"), (int, float)) and part["exit_code"] == 0 else {})}
        rerun = item.get("rerun")
        if isinstance(rerun, dict) and part["exit_code"] != 0:
            result["rerun"] = {**_run_part(rerun), "tests": _ids(rerun.get("tests"))}
            result["flaky"] = _ids(item.get("flaky"))  # failed, then passed in the re-run
        results.append(result)
    return results


def _judge_flaky(run: WorkflowRun, results: list[dict[str, Any]]) -> list[str]:
    """Split each command's flaky tests into first-time (not counted) and again (red); record them on the run.
    Returns every flaky test id of this pass."""
    history = dict(dict(run.context or {}).get(FLAKY_KEY) or {})
    seen: list[str] = []
    for item in results:
        flaky = list(item.get("flaky") or [])
        item["flaky_again"] = [test for test in flaky if int(history.get(test) or 0) > 0]
        seen.extend(test for test in flaky if test not in seen)
    for test in seen:
        history[test] = int(history.get(test) or 0) + 1
    if seen:
        run.context = {**dict(run.context or {}), FLAKY_KEY: history}
    return seen


def _test_run(run: WorkflowRun, item: dict[str, Any], proofs: list[str]) -> dict[str, Any]:
    """One command as a recorded test run with a result per test: its JUnit report first (resolved with the test
    files the launcher found and the task list's proof files), else what its output printed."""
    from ..workflow_checks.test_output import hint_files, parse, parse_junit
    from .test_resolution import resolver_for

    files = hint_files(item["junit_files"])
    resolver = resolver_for(run, proofs, files)
    parsed = parse_junit(item["junit_xml"], resolver) if item["junit_xml"] else None
    if parsed is None or not (parsed.results or parsed.unresolved):
        printed = parse(item["output_tail"], resolver, item["command"])
        printed.problems = [*(parsed.problems if parsed else []), *printed.problems]
        parsed = printed
    return {"source": "pipeline", "command": item["command"], "exit_code": item["exit_code"],
            "all_green": _green(item), "stdout": item["output_tail"], **parsed.fields(),
            **({"files": files} if files else {})}


def _failed_tests(test_run: dict[str, Any]) -> list[str]:
    return [test_id for test_id, result in dict(test_run.get("results") or {}).items()
            if dict(result).get("outcome") in ("failed", "error")]


def _failed_line(item: dict[str, Any]) -> str:
    tests = item.get("failed_tests") or []
    again = item.get("flaky_again") or []
    line = f"{item['command']} failed" + (f" ({', '.join(tests)})" if tests else "")
    return line + (f"; flaky again: {', '.join(again)}" if again else "")


def _stored(item: dict[str, Any]) -> dict[str, Any]:
    """A command's result as the run keeps it: no JUnit text (its tests are recorded as test runs)."""
    kept = {key: value for key, value in item.items() if key not in ("junit_xml", "junit_files")}
    if isinstance(kept.get("rerun"), dict):
        kept["rerun"] = {key: value for key, value in kept["rerun"].items() if key not in ("junit_xml", "junit_files")}
    return kept
