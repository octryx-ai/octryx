"""Per-test results from octryx-claude's hooks.

At ``Stop`` / ``SubagentStop`` the gateway already knows the session's Bash calls and which of them are test
commands: the same prefixes the run's phase evidence uses (``octryx.hooks.test_prefixes``: the Workspace's
``test_command_prefixes``, else the platform defaults), so a test run the phase counts is always recorded — a
Workspace without a verification policy also records a device's red run. When the session is bound
to an active workflow run, the newest test call's recorded result excerpt is read into a test run (``source:
octryx``) on that run by the chat's own ``record_turn_test_runs``, so the run's TDD gates judge the same evidence
chat produces (the first red also fixes the confirmed tests' content). The JUnit report the declared test command
wrote, when the launcher attached it to the call (``agent_gateway/tool_execution.test_report``), is the preferred
source of the per-test results; the output excerpt is the fallback (:func:`bash_test_results`). Results are keyed by
the canonical test id (``workflow_checks.test_ids``); the files the launcher found for the report's classnames travel
with the run so the server resolves them without the device's tree (``test_resolution``). A test command
whose runner executed no test (``test_command_outcome``: not installed, nothing collected) is no test run and is not
recorded. A session that follows no run is untouched.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ToolCall
from ..workflow_checks.test_command_outcome import RAN, classify
from ..workflow_checks.test_output import ERROR, FAILED, ParsedTests, hint_files, parse
from .records import active_run_for_session, lock_run
from .test_runs import record_turn_test_runs


def bash_test_results(parameters: Any, excerpt: str) -> tuple[ParsedTests, list[str]]:
    """A device test call's per-test results — its attached JUnit report first, else what its output printed — and
    the test files the launcher found for the report (resolution hints)."""
    from ..agent_gateway.tool_execution import TEST_REPORT_KEY

    report = parameters.get(TEST_REPORT_KEY) if isinstance(parameters, dict) else None
    xml = report.get("junit_xml") if isinstance(report, dict) else None
    files = hint_files(report.get("files")) if isinstance(report, dict) else []
    parsed = parse(xml) if isinstance(xml, str) else ParsedTests()
    if parsed.results or parsed.unresolved:
        return parsed, files
    command = str(parameters.get("command") or "") if isinstance(parameters, dict) else ""
    printed = parse(excerpt, command=command)
    if printed.suite_passed and _selects_part(command):
        printed.suite_passed = 0  # only the whole suite stands for every test
    printed.problems = [*parsed.problems, *printed.problems]
    return printed, files


_NAME_FILTERS = ("--plain-name", "--name", "-n", "--tags", "-t", "--exclude-tags", "-x")


def _selects_part(command: str) -> bool:
    """Whether a Dart test command runs only part of the suite (a test file or folder, a name or tag filter)."""
    words = command.replace("|", " | ").split()
    if "|" in words:
        words = words[:words.index("|")]
    return any(word.endswith(".dart") or word.startswith(("test/", "integration_test/")) or word in _NAME_FILTERS
               or word.startswith(tuple(f"{name}=" for name in _NAME_FILTERS if name.startswith("--")))
               for word in words)


def gateway_test_run(parsed: ParsedTests, files: list[str], *, green: bool) -> dict[str, Any]:
    return {"source": "octryx", "all_green": green, **parsed.fields(), **({"files": files} if files else {})}


async def record_gateway_tests(
    db: AsyncSession, *, session_id: str, policy: Any, tool_calls: Sequence[ToolCall]
) -> bool:
    run = await active_run_for_session(db, session_id)
    if run is None:
        return False
    from ..agent_gateway.command_match import command_segments, segment_matches
    from ..agent_gateway.verification import BASH_TOOL, _order_key, _parameters
    from .octryx.hooks import test_prefixes

    prefixes = test_prefixes(policy)

    def is_test(row: ToolCall) -> bool:
        segments = command_segments(str(_parameters(row).get("command") or "")) if row.tool_name == BASH_TOOL else None
        return bool(segments) and any(segment_matches(segment, prefix) for segment in segments for prefix in prefixes)

    tests = sorted((row for row in tool_calls if is_test(row)), key=_order_key)
    if not tests:
        return False
    last = tests[-1]
    result = last.result if isinstance(last.result, dict) else {}
    excerpt = str(result.get("excerpt") or "")
    green = last.status == "success" and result.get("is_error") is False
    parsed, files = bash_test_results(_parameters(last), excerpt)
    outcome = classify({**result, "exit_code": 0} if green else result,
                       command=str(_parameters(last).get("command") or ""), parsed_results=parsed.executed())
    if outcome.kind != RAN:
        return False  # no test ran: nothing to record (the phase's evidence says why)
    run = await lock_run(db, run)
    seen = dict(run.context or {}).get("tests", {}).get("octryx_last_call") if isinstance(
        dict(run.context or {}).get("tests"), dict) else None
    if seen == last.id:
        return False
    # The chat's own recorder: the first red also fixes the confirmed tests' content (on a device: the launcher's
    # next report is their baseline), so the green gate can verify them.
    # A failing test is never green, also when a pipe (``| tail``) made the command's own status 0
    # (else a red Dart run is recorded all_green).
    failing = any(value.get("outcome") in (FAILED, ERROR) for value in parsed.results.values())
    green = result.get("is_error") is False and not failing
    await record_turn_test_runs(db, run, [gateway_test_run(parsed, files, green=green)],
                                node_id=run.current_node_id)
    tests_state = dict(dict(run.context or {}).get("tests") or {})
    tests_state["octryx_last_call"] = last.id
    run.context = {**dict(run.context or {}), "tests": tests_state}
    return True


__all__ = ["bash_test_results", "gateway_test_run", "record_gateway_tests"]
