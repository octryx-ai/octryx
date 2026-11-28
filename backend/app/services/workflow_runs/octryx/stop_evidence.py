"""The phase's evidence at Stop: the session's recorded tool calls since the phase was entered, as check inputs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ....models import ToolCall, WorkflowRun
from ...agent_gateway.capability import FILE_MUTATION_TOOLS, PLATFORM_MCP_TOOL_PREFIX
from ...agent_gateway.command_match import command_segments, segment_matches
from ...agent_gateway.read_evidence import native_read_use, native_web_use
from ...model_gateway.inbound.seat_transcript import HOSTED_SEARCH_TOOL
from ...observability.knowledge_metrics import knowledge_hits, web_result_ok
from ...workflow_checks.library import ToolUse, TurnEvidence
from ...workflow_checks.test_command_outcome import NOT_RUN_TOOL, RAN, classify, environment_failure
from ..gateway_tests import bash_test_results, gateway_test_run
from .declared_commands import declared_command, declared_commands
from .facts import FACTS_KEY
from .tool_policy import CODEX_SEARCH_TOOLS


def _parameters(row: ToolCall) -> dict[str, Any]:
    return row.parameters if isinstance(row.parameters, dict) else {}


def _green(row: ToolCall) -> bool:
    result = row.result if isinstance(row.result, dict) else None
    return row.status == "success" and result is not None and result.get("is_error") is False


KNOWLEDGE_HIT = "knowledge_hit"
LINT_TOOL = "declared_lint"


def declared_lint(contract: dict[str, Any]) -> tuple[str, ...]:
    environment = dict(contract.get("preparation") or {}).get("environment")
    lint = str(environment.get("lint") or "").strip() if isinstance(environment, dict) else ""
    return (lint,) if lint and declared_commands(environment) else ()


def written_files(run: WorkflowRun, hook_input: dict[str, Any]) -> dict[str, str]:
    from ...workflow_checks.urls import added_lines

    facts = hook_input.get(FACTS_KEY) if isinstance(hook_input.get(FACTS_KEY), dict) else {}
    change = facts.get("change") if isinstance(facts.get("change"), dict) else None
    if change is None or not isinstance(change.get("patch"), str):
        recorded = dict(dict(run.context or {}).get("device_change") or {})
        current = (recorded.get("node_id") == run.current_node_id
                   and recorded.get("entry") == dict(run.node_state or {}).get("entry"))
        change = recorded if current else {}
    return added_lines(str(change.get("patch") or ""))


def _since(run: WorkflowRun) -> datetime | None:
    try:
        return datetime.fromisoformat(str(dict(run.node_state or {}).get("entered_at") or "")).replace(tzinfo=None)
    except ValueError:
        return None


def phase_evidence(rows: Sequence[ToolCall], *, since: datetime | None,
                   test_prefixes: tuple[tuple[str, ...], ...], checks: tuple[str, ...] = (),
                   system: tuple[str, ...] = ()) -> TurnEvidence:
    from ...workflow_checks.test_results import chat_verification_state

    uses: list[ToolUse] = []
    runs: list[dict[str, Any]] = []
    outcomes: list[tuple[Any, str, str]] = []
    for row in sorted(rows, key=lambda item: item.created_at or datetime.min):
        if since is not None and (row.created_at is None or row.created_at < since):
            continue
        name = str(row.tool_name or "")
        result = row.result if isinstance(row.result, dict) else {}
        read = native_read_use(row) or native_web_use(row)
        if read is not None:
            uses.append(read)
        elif name in CODEX_SEARCH_TOOLS:
            uses.append(ToolUse("web_search", _green(row), row.result))
        elif name == HOSTED_SEARCH_TOOL:
            uses.append(ToolUse("web_search", _green(row), row.result))
        elif name.startswith(PLATFORM_MCP_TOOL_PREFIX):
            tool = name.removeprefix(PLATFORM_MCP_TOOL_PREFIX)
            uses.append(ToolUse(tool, _green(row) and web_result_ok(tool, result), row.result))
            if tool == "knowledge_search" and _green(row) and knowledge_hits(result):
                # Knowledge-first: a knowledge search that found something is research evidence.
                uses.append(ToolUse(KNOWLEDGE_HIT, True, row.result))
        elif name in FILE_MUTATION_TOOLS:
            uses.append(ToolUse("edit_workspace_file", _green(row) or row.status == "success"))
        elif name == "Bash" and system and declared_command(str(_parameters(row).get("command") or ""), system):
            uses.append(ToolUse("run_system_tests", _green(row), row.result))
        elif name == "Bash":
            _bash_evidence(row, result, test_prefixes, checks, uses=uses, runs=runs, outcomes=outcomes)
    state = chat_verification_state(uses, test_prefixes)
    return TurnEvidence(tools=uses, verification_state=None if state == "not_applicable" else state, test_runs=runs,
                        environment_failure=environment_failure(outcomes))


def _bash_evidence(row: ToolCall, result: dict[str, Any], test_prefixes: tuple[tuple[str, ...], ...],
                   checks: tuple[str, ...], *, uses: list[ToolUse], runs: list[dict[str, Any]],
                   outcomes: list[tuple[Any, str, str]]) -> None:
    segments = command_segments(str(_parameters(row).get("command") or "")) or []
    if segments and any(segment_matches(segment, prefix) for segment in segments for prefix in test_prefixes):
        green = _green(row)
        excerpt = str(result.get("excerpt") or "")
        command = str(_parameters(row).get("command") or "")
        parsed, files = bash_test_results(_parameters(row), excerpt)
        # Only a command whose runner executed tests is a test run; one that could not start is the
        # environment's (``test_command_outcome``), never the phase's evidence.
        outcome = classify({**result, "exit_code": 0} if green else result, command=command,
                           parsed_results=parsed.executed())
        outcomes.append((outcome, command, excerpt))
        if outcome.kind != RAN:
            uses.append(ToolUse(NOT_RUN_TOOL, False, outcome.as_dict(command, excerpt)))
            return
        uses.append(ToolUse("run_test_suite", True, {"exit_code": 0 if green else 1, "stdout": excerpt,
                                                     "all_green": green}))
        runs.append(gateway_test_run(parsed, files, green=green))
    elif checks and declared_command(str(_parameters(row).get("command") or ""), checks):
        uses.append(ToolUse(LINT_TOOL, _green(row), row.result))
    else:
        uses.append(ToolUse("bash", _green(row), row.result, {"command": _parameters(row).get("command")}))
