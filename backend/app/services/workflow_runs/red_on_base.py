"""The reproduction's tests run once more on the run's base commit: each must fail there.

a test that asserts the reported wrong
behaviour sent small items back and forth between reproduce and fix, and the reproduces gate refused a corrected
existing test ("only a new test can be red"). The device checks out the base commit in a temporary worktree, puts
this change's test files there and runs only them with the repository's test command (``octryx-claude``'s
``red_on_base``). A test that fails there reproduces the bug, new or corrected; one that passes does not, and a changed
test file that names no reproduction test (a weakened test nobody named) shows up as well. That proves the reproduction
on code the agent cannot have changed.

Two places ask for it, both as data:
- a size class's ``"red_on_base": true``: the pipeline after the fix (the small item that reproduces and fixes in one
  phase, ``size_class/merge``); a test that passes on the base keeps the pipeline red (:func:`judge`);
- a reproduce check's ``"red_on_base": true`` (``hands_on.run`` in mode ``reproduce``): before the fix, for the
  submitted reproduction; the reproduces gate reads the verdict (``existing_tests: red_on_base``).
Either way the verdict is kept as ``context["red_on_base"]`` (:func:`record`), the one place the gates read it.
"""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRun

CLASS_KEY = "red_on_base"
CONTEXT_KEY = "red_on_base"
ERRORS_KEY = "red_on_base_errors"
FAILED, ERROR, PASSED, MISSING = "failed", "error", "passed", "missing"
STATE_UNATTRIBUTED = "unattributed"  # the platform's evidence gap: one pause with cause platform, no round


def _asked(run: WorkflowRun, tests: list[str], app_folder: str) -> dict[str, Any] | None:
    from ..engineering_knowledge.stacks import is_test
    from ..workflow_checks.test_ids import file_of
    from .octryx.system_tests import changed_files

    context = dict(run.context or {})
    base = str(context.get("base_sha") or "")
    if not base or not tests:
        return None
    prefix = "" if app_folder in ("", ".") else f"{app_folder.strip('/')}/"
    # Every changed test file runs there too, so one that holds no named test (a weakened test) shows up.
    # Judged from the app folder (otherwise e2e/node/src/books.js counted as a test because the
    # repository's "e2e" folder is a test folder name).
    changed = [name[len(prefix):] for name in changed_files(context.get("device_change")) or []
               if name.startswith(prefix) and is_test(name[len(prefix):])]
    files = list(dict.fromkeys([*(file_of(test) for test in tests if file_of(test)), *changed]))
    from ..engineering_knowledge.stacks import all_report_env, only_files_specs

    # The base run writes the platform's per-test report (stacks.json report_env): a runner whose output names no
    # file per test (node's spec reporter) is attributed exactly. How a runner runs only
    # these files is data too (``only_files``); a command without a template runs in full.
    return {"base": base, "tests": tests, "files": files, "report_env": all_report_env(),
            "only_files": only_files_specs(),
            **({"changed": changed} if changed else {})}


def request(run: WorkflowRun, app_folder: str = ".") -> dict[str, Any] | None:
    """The pipeline's base run for the confirmed tests when the run's size class asks for it; else ``None``."""
    from .size_class import class_config
    from .test_runs import confirmed_tests

    if class_config(run).get(CLASS_KEY) is not True:
        return None
    return _asked(run, confirmed_tests(run), app_folder)


def before_fix(run: WorkflowRun, node: Any, app_folder: str = ".") -> dict[str, Any] | None:
    """A reproduce check's base run for the submitted reproduction's tests when its node asks for it."""
    from ..workflow_checks.test_ids import normalize
    from .phase_outputs import recorded_output

    if dict(getattr(node, "config", None) or {}).get(CLASS_KEY) is not True:
        return None
    record = dict(dict(recorded_output(run, "reproduction") or {}).get("record") or {})
    tests = [normalize(test) for test in record.get("tests") or [] if normalize(test)]
    return _asked(run, list(dict.fromkeys(tests)), app_folder)


def _start_folder(command: str) -> str:
    """The start folder of a ``unittest discover`` command (``-s``/``--start-directory``): its tests are named
    relative to it (``test_pricing.PricingTest`` for ``tests/test_pricing.py``), so the asked id is read without it."""
    words = str(command or "").split()
    if "discover" not in words:
        return ""
    for index, word in enumerate(words):
        if word in ("-s", "--start-directory") and index + 1 < len(words):
            return words[index + 1].strip("'\"").removeprefix("./").rstrip("/")
        if word.startswith("--start-directory="):
            return word.split("=", 1)[1].strip("'\"").removeprefix("./").rstrip("/")
    return ""


def outcomes(requested: dict[str, Any], report: dict[str, Any]) -> dict[str, str]:
    """Each asked test's result on the base: ``failed``, ``error`` (a file that does not load counts), ``passed`` or
    ``missing``."""
    from ..workflow_checks.test_output import ERROR as PARSED_ERROR
    from ..workflow_checks.test_output import FAILED as PARSED_FAILED
    from ..workflow_checks.test_output import SCOPE_COLLECTION, parse

    parsed = parse(str(report.get("junit_xml") or report.get("output_tail") or ""),
                   command=str(report.get("command") or ""))
    broken = {test_id.split("::", 1)[0] for test_id, value in parsed.results.items()
              if value.get("scope") == SCOPE_COLLECTION}
    # A runner whose output names no file (node's spec reporter): a name only one asked test has is that test.
    asked = [str(test) for test in requested.get("tests") or []]
    by_name = {}
    for item in parsed.unresolved:
        owners = [test for test in asked if test.split("::", 1)[-1] == item.get("name")]
        if len(owners) == 1 and not item.get("file") and item.get("outcome"):
            by_name[owners[0]] = {"outcome": PARSED_FAILED if item["outcome"] == "failed" else item["outcome"]}
    start = _start_folder(str(report.get("command") or ""))
    out = {}
    for test in requested.get("tests") or []:
        relative = test[len(start) + 1:] if start and start != "." and test.startswith(start + "/") else ""
        outcome = dict(parsed.results.get(test) or (parsed.results.get(relative) if relative else None)
                       or by_name.get(test) or {}).get("outcome")
        out[test] = (FAILED if outcome == PARSED_FAILED else ERROR if outcome == PARSED_ERROR or
                     {test.split("::", 1)[0], relative.split("::", 1)[0]} & broken else
                     PASSED if outcome else MISSING)
    return out


NO_TEST_TAIL = 600


def no_test_started(report: Any) -> str:
    """Why nothing could be attributed when the base run ran but started no test at all (its output names no test
    result): the command and the end of its output, else ``""`` (e.g. a unittest discover with a
    file argument failed on import and paused as "could not attribute" without saying so)."""
    from ..workflow_checks.test_output import parse

    if not isinstance(report, dict) or report.get("exit_code") is None:
        return ""
    parsed = parse(str(report.get("junit_xml") or report.get("output_tail") or ""),
                   command=str(report.get("command") or ""))
    if parsed.results or parsed.unresolved:
        return ""
    from ...services.redaction_policy import redact_secret_text

    tail = redact_secret_text(str(report.get("output_tail") or "").strip()[-NO_TEST_TAIL:])
    return (f"the base run started no test (`{report.get('command') or 'its command'}`, exit code "
            f"{report.get('exit_code')}); the end of its output: {tail or '(none)'}")


def unnamed(requested: dict[str, Any]) -> list[str]:
    from ..workflow_checks.test_ids import file_of

    named = {file_of(test) for test in requested.get("tests") or []}
    return [name for name in requested.get("changed") or [] if name not in named]


def judge(requested: dict[str, Any] | None, report: Any) -> list[str]:
    """What keeps the pipeline red: a changed test file nobody named, each test that did not fail on the base, or a
    run that never happened."""
    if not requested:
        return []
    if not isinstance(report, dict) or report.get("exit_code") is None:
        reason = str(dict(report or {}).get("reason") or "it did not run") if isinstance(report, dict) else \
            "it did not run"
        return [f"the confirmed tests could not run on the base commit ({reason})"]
    errors = [f"{name} changed, but none of its tests is in the reproduction: name the tests that show the bug, or "
              "undo the change" for name in unnamed(requested)]
    for test, outcome in outcomes(requested, report).items():
        if outcome == PASSED:
            errors.append(f"{test} passes on the base commit: it does not reproduce the bug")
    return errors  # a test the base run did not show is the platform's to attribute (:func:`unattributed`), never this


def unattributed(requested: dict[str, Any] | None, report: Any) -> list[str]:
    """The asked tests the base run showed no result for that the platform could attribute: its own evidence gap
    and never "passes on base" or a round for the agent."""
    if not requested or not isinstance(report, dict) or report.get("exit_code") is None:
        return []
    return [test for test, outcome in outcomes(requested, report).items() if outcome == MISSING]


def record(run: WorkflowRun, requested: dict[str, Any] | None, report: Any, *, node_id: str, entry: Any,
           environment: str = "") -> None:
    """The verdict as ``context["red_on_base"]`` (the shape the reproduces gate reads)."""
    if not requested:
        return
    report = report if isinstance(report, dict) else {}
    ran = report.get("exit_code") is not None and not environment
    tests = outcomes(requested, report) if ran else {test: MISSING for test in requested.get("tests") or []}
    errors = judge(requested, report) if ran else []
    missing = unattributed(requested, report) if ran and not errors else []
    state = "environment" if not ran else "not_proven" if errors else STATE_UNATTRIBUTED if missing else "proven"
    reason = environment or (report.get("reason") if not ran else "; ".join(errors)) or (
        (no_test_started(report) or
         f"no result on the base commit the platform could attribute: {', '.join(missing[:5])}") if missing else "")
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {
        "base": requested.get("base"), "node_id": node_id, "entry": entry, "tests": tests,
        "files_changed": list(requested.get("changed") or []), "unnamed_changes": unnamed(requested),
        "state": state, "reason": str(reason)[:2000]}}


async def environment_failure(db: Any, run: WorkflowRun, requested: dict[str, Any] | None,
                              report: Any) -> dict[str, Any] | None:
    """The base run the environment could not do (no checkout, a failed setup, a timeout, or an output the stack data
    names an environment error): the ``environment_not_ready`` pause, never a fix round."""
    from ..workflow_checks.test_command_outcome import MAX_EXCERPT
    from .pipeline_environment import SOURCE
    from .pipeline_environment import environment_failure as command_failure

    if not requested:
        return None
    report = report if isinstance(report, dict) else {"reason": "it did not run"}
    if report.get("exit_code") is None:
        return {"kind": "environment", "source": SOURCE, "command": str(report.get("command") or ""),
                "exit_code": None, "excerpt": str(report.get("output_tail") or "")[-MAX_EXCERPT:],
                "reason": f"the device could not run the tests on the base commit: "
                          f"{report.get('reason') or 'it did not run'}"}
    if not report.get("exit_code"):
        return None  # a green base run: nothing failed to run
    item = {key: report.get(key) for key in ("command", "exit_code", "output_tail")}
    return await command_failure(db, run, [item])


__all__ = ["CLASS_KEY", "CONTEXT_KEY", "ERRORS_KEY", "before_fix", "environment_failure", "judge", "outcomes",
           "record", "request", "unattributed", "unnamed"]
