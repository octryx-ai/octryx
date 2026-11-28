"""Per-test results and the TDD checks over them."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .test_ids import covers, is_canonical, selects
from .test_output import ERROR, FAILED, PASSED, SKIPPED, ParsedTests, parse

TEST_TOOLS = frozenset({"run_test_suite"})
CHANGE_TOOLS = frozenset({"write_workspace_file", "edit_workspace_file", "multi_edit_workspace_file",
                          "apply_patch_workspace"})
SHELL_TOOLS = frozenset({"bash"})
DEFAULT_TEST_PREFIXES: tuple[tuple[str, ...], ...] = (("pytest",), ("python", "-m", "pytest"),
                                                       ("python3", "-m", "pytest"), ("flutter", "test"),
                                                       ("dart", "test"))


def parse_test_output(text: str) -> dict[str, dict[str, str]]:
    return parse(text).results


def test_run_from_tool(name: str, result: Any, *, source: str, command: str = "") -> dict[str, Any] | None:
    if name not in TEST_TOOLS or not isinstance(result, Mapping) or result.get("error"):
        return None
    report = result.get("test_report") if isinstance(result.get("test_report"), Mapping) else {}
    if report.get("fresh") is True and isinstance(report.get("results"), Mapping):
        # The JUnit report this very execution wrote, resolved against the run's copy (``declared_tests``).
        parsed = ParsedTests(dict(report["results"]), list(report.get("unresolved") or []),
                             list(report.get("problems") or []))
    else:
        parsed = parse(f"{result.get('stdout') or ''}\n{result.get('stderr') or ''}",
                       command=command or str(result.get("command") or ""))
    results = parsed.results
    reported = result.get("failed_tests")
    if isinstance(reported, list) and (reported or result.get("exit_code") == 0):
        # The runner's own failure list decides which tests failed; a printed FAILED line for another test is not.
        from .test_ids import normalize

        failed = {normalize(item) for item in reported}
        results = {test_id: value for test_id, value in results.items()
                   if value["outcome"] not in (FAILED, ERROR) or test_id in failed}
        for test_id in failed:
            results.setdefault(test_id, {"outcome": FAILED, "message": ""})
    exit_code = result.get("exit_code", result.get("returncode"))
    green = result.get("all_green") is True or (exit_code == 0 and result.get("all_green") is not False)
    return {"source": source, **ParsedTests(results, parsed.unresolved, parsed.problems).fields(),
            "all_green": bool(green)}


def is_test_command(use: Any, prefixes: Iterable[Iterable[str]] = DEFAULT_TEST_PREFIXES) -> bool:
    from ..agent_gateway.command_match import command_segments, segment_matches

    if use.name not in SHELL_TOOLS:
        return False
    params = use.params if isinstance(use.params, Mapping) else {}
    segments = command_segments(str(params.get("command") or ""))
    return bool(segments) and any(segment_matches(segment, tuple(prefix))
                                  for segment in segments for prefix in prefixes)


def test_run_from_use(use: Any, *, source: str,
                      prefixes: Iterable[Iterable[str]] = DEFAULT_TEST_PREFIXES) -> dict[str, Any] | None:
    if use.name in TEST_TOOLS:
        return test_run_from_tool(use.name, use.result, source=source)
    if not is_test_command(use, prefixes) or not isinstance(use.result, Mapping):
        return None
    params = use.params if isinstance(use.params, Mapping) else {}
    return test_run_from_tool("run_test_suite", use.result, source=source, command=str(params.get("command") or ""))


def is_change(use: Any, prefixes: Iterable[Iterable[str]] = DEFAULT_TEST_PREFIXES) -> bool:
    if use.name in CHANGE_TOOLS:
        return bool(use.succeeded)
    return use.name in SHELL_TOOLS and not is_test_command(use, prefixes)


def _selected(confirmed: str, test_id: str, value: Mapping[str, Any]) -> bool:
    return selects(confirmed, test_id) or (value.get("scope") == "collection" and covers(test_id, confirmed))


def confirmed_outcomes(run: Mapping[str, Any], confirmed: Iterable[str]) -> dict[str, list[dict[str, str]]]:
    results = dict(run.get("results") or {})
    found = {item: [value for test_id, value in results.items() if _selected(item, test_id, value)]
             for item in confirmed}
    if run.get("suite_passed"):
        # The whole suite passed (a Dart run that ended "All tests passed!", none skipped; its output, cut by a
        # pipe, may not name every test): a confirmed test it does not name passed with it
        # (e.g. `flutter test | tail -3`). A deleted or rewritten confirmed test is still caught by the content drift.
        found = {item: values or [{"outcome": PASSED, "message": "", "scope": "suite"}]
                 for item, values in found.items()}
    return found


def evidence_unresolved(run: Mapping[str, Any], confirmed: list[str], *, suite: bool = False) -> list[str]:
    reasons = [f"{item}: not a canonical test id (path/to/test_file.py::test)" for item in confirmed
               if not is_canonical(item)]
    unresolved = [item for item in run.get("unresolved") or [] if isinstance(item, Mapping)]
    problems = [str(item) for item in run.get("problems") or []]
    if unresolved or problems:
        unseen = [item for item, outcomes in confirmed_outcomes(run, confirmed).items()
                  if not outcomes and is_canonical(item)]
        if unseen:
            detail = "; ".join([*(f"{item.get('raw')}: {item.get('reason')}" for item in unresolved[:3]),
                                *problems[:2]])
            reasons.append(f"not seen: {', '.join(unseen[:5])} — the run's results could not all be keyed "
                           f"({len(unresolved)} unresolved: {detail})")
    if suite:
        broken = [item for item in unresolved if item.get("outcome") in (FAILED, ERROR)]
        if broken:
            reasons.append("failing tests with an unresolved id (regression or reproduction cannot be told): "
                           + "; ".join(f"{item.get('raw')}: {item.get('reason')}" for item in broken[:3]))
    return reasons


_MISSING_MODULE = ("modulenotfounderror", "no module named", "importerror: cannot import name")


def _missing_module(value: Mapping[str, Any]) -> bool:
    message = str(value.get("message") or "").lower()
    return any(marker in message for marker in _MISSING_MODULE)


def all_red(run: Mapping[str, Any], confirmed: list[str],
            roles: Mapping[str, str] | None = None) -> tuple[bool, str]:
    roles = roles or {}
    new = [item for item in confirmed if roles.get(item) != "regression"]
    if not new:
        return False, "no new confirmed test (a regression test passes; only a new test can be red)"
    for item, outcomes in confirmed_outcomes(run, confirmed).items():
        if not outcomes:
            return False, f"{item}: not seen in the last test run"
        if item not in new:
            if not all(value["outcome"] == PASSED for value in outcomes):
                return False, f"{item}: regression test does not pass (an existing test must keep passing)"
            continue
        if any(value["outcome"] == ERROR for value in outcomes):
            if all(value["outcome"] != ERROR or _missing_module(value) for value in outcomes):
                continue  # new code: the module under test does not exist yet
            return False, f"{item}: errors before its assertions (it must fail on an assertion)"
        if not any(value["outcome"] == FAILED for value in outcomes):
            return False, f"{item}: does not fail (a new test must fail on an assertion before the change)"
    return True, ""


def suite_regressions(run: Mapping[str, Any], confirmed: list[str]) -> list[str]:
    return sorted(test_id for test_id, value in dict(run.get("results") or {}).items()
                  if value.get("outcome") in (FAILED, ERROR)
                  and not any(_selected(item, test_id, value) for item in confirmed))


def all_green(run: Mapping[str, Any], confirmed: list[str]) -> tuple[bool, str]:
    broken = [test_id for test_id, value in dict(run.get("results") or {}).items()
              if value.get("outcome") in (FAILED, ERROR)]
    broken += [str(item.get("raw")) for item in run.get("unresolved") or []
               if isinstance(item, Mapping) and item.get("outcome") in (FAILED, ERROR)]
    if broken:
        return False, f"failing: {', '.join(sorted(broken)[:5])}"
    if not run.get("all_green"):
        return False, "the test command did not pass"
    for item, outcomes in confirmed_outcomes(run, confirmed).items():
        if not outcomes or not all(value["outcome"] == PASSED for value in outcomes):
            return False, f"{item}: not passed in the last test run"
    return True, ""


def intact(run: Mapping[str, Any], confirmed: list[str]) -> tuple[bool, str]:
    if not confirmed:
        return False, "no confirmed tests"
    for item, outcomes in confirmed_outcomes(run, confirmed).items():
        if not outcomes:
            return False, f"{item}: missing from the last test run (deleted or not run)"
        if any(value["outcome"] == SKIPPED for value in outcomes):
            return False, f"{item}: skipped"
    return True, ""


def chat_verification_state(uses: Iterable[Any], prefixes: Iterable[Iterable[str]] = DEFAULT_TEST_PREFIXES) -> str:
    sequence = list(uses)
    prefixes = tuple(tuple(item) for item in prefixes)
    last_change = max((index for index, use in enumerate(sequence) if is_change(use, prefixes)), default=-1)
    if last_change < 0:
        return "not_applicable"
    runs = [test_run_from_use(use, source="chat", prefixes=prefixes) for use in sequence[last_change + 1:]]
    runs = [item for item in runs if item is not None]
    if not runs:
        return "no_test_after_last_change"
    return "passed" if runs[-1]["all_green"] else "last_test_failed"


__all__ = [
    "CHANGE_TOOLS",
    "DEFAULT_TEST_PREFIXES",
    "SHELL_TOOLS",
    "TEST_TOOLS",
    "all_green",
    "all_red",
    "chat_verification_state",
    "confirmed_outcomes",
    "evidence_unresolved",
    "intact",
    "is_change",
    "is_test_command",
    "parse_test_output",
    "suite_regressions",
    "test_run_from_tool",
    "test_run_from_use",
]
