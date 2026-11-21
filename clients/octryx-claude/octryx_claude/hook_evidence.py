"""Evidence and context the hook commands add to what they send (``hooks``): the run contract's working copy
facts, the declared test command's report, the run's launcher texts and the remembered contract. Best effort
throughout: none of it ever fails a hook."""

from __future__ import annotations

import os
import re
from typing import Any

from . import run_contract, test_report
from .content_hooks import route_notice_once
from .launch_process import PROFILE_SEAT
from .platform import ENV_PROFILE, PlatformResult, SessionContext
from .state import LocalState


def launcher_texts(state: LocalState, context: SessionContext | None) -> dict[str, Any]:
    """The platform's launcher texts of this session's run (the cached contract's ``prompt_texts``, ``run.launcher.*``);
    empty without a run, then :func:`pipeline.text` uses the launcher's fallbacks."""
    if context is None:
        return {}
    try:
        contract = run_contract.current(state, context.session_key)
    except Exception:  # noqa: BLE001 - a text never fails a hook
        return {}
    return dict((contract or {}).get("prompt_texts") or {}) if isinstance(contract, dict) else {}


def _route_notice(state: LocalState, context: SessionContext, result: PlatformResult) -> str:
    """A conversation the gateway routed by a content policy is announced once (best effort)."""
    try:
        return route_notice_once(state, context.session_key, result.body if result.outcome == "ok" else None,
                                 seat=os.environ.get(ENV_PROFILE) == PROFILE_SEAT)
    except Exception:  # noqa: BLE001 - a notice never disturbs the hook
        return ""


def _with_facts(state: LocalState, context: SessionContext, hook_input: dict[str, Any], *,
                with_diff: bool) -> dict[str, Any]:
    """The hook input plus the working copy's facts the remembered run contract asks for (best effort)."""
    try:
        reported = run_contract.facts(run_contract.current(state, context.session_key),
                                      root=run_contract.project_root(str(hook_input.get("cwd") or "")),
                                      with_diff=with_diff, hook_input=hook_input)
    except Exception:  # noqa: BLE001 - facts never block a hook; the server then lacks them and stays strict
        reported = None
    return {**hook_input, run_contract.FACTS_KEY: reported} if reported else hook_input


def _note_system_test_run(state: LocalState, context: SessionContext, hook_input: dict[str, Any]) -> None:
    """The start of a run of the declared system test command: the review's screenshots are that run's (best
    effort)."""
    try:
        from . import screens  # noqa: PLC0415

        screens.note_run(state.session_dir(context.session_key), run_contract.current(state, context.session_key),
                         hook_input)
    except Exception:  # noqa: BLE001 - evidence only; the tool decision never depends on it
        pass


def _note_test_report(state: LocalState, context: SessionContext, hook_input: dict[str, Any]) -> None:
    try:
        test_report.before(state, context.session_key, run_contract.current(state, context.session_key), hook_input,
                           run_contract.project_root(str(hook_input.get("cwd") or "")))
    except Exception:  # noqa: BLE001 - the report is evidence only; the tool decision never depends on it
        pass


_PERSISTED = re.compile(r"Full output saved to: (?P<path>/\S+/tool-results/[\w.-]+\.txt)")
PERSISTED_TAIL = 16_000
MAX_TEST_BRIEF = 6000  # the platform's brief (``workflow_checks/test_brief``), bounded here too


def with_full_output_tail(hook_input: dict[str, Any]) -> dict[str, Any]:
    """A Bash result Claude Code cut to a preview (``<persisted-output>`` … "Full output saved to: <file>") gets the
    end of that file appended, so the platform reads the command's closing lines (the preview holds only the
    first 2 KB, where a long test run's result is not). Only a ``tool-results/*.txt`` file of Claude Code's own."""
    response = hook_input.get("tool_response")
    if hook_input.get("tool_name") != "Bash" or not isinstance(response, dict):
        return hook_input
    stdout = str(response.get("stdout") or "")
    match = _PERSISTED.search(stdout)
    if not match:
        return hook_input
    try:
        with open(match["path"], "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - PERSISTED_TAIL))
            tail = handle.read().decode("utf-8", "replace")
    except OSError:
        return hook_input
    return {**hook_input, "tool_response": {**response, "stdout": f"{stdout}\n…\n{tail}"}}


def _with_test_report(state: LocalState, context: SessionContext, hook_input: dict[str, Any]) -> dict[str, Any]:
    """The hook input plus the JUnit report the declared test command wrote in this call (best effort)."""
    hook_input = with_full_output_tail(hook_input)
    try:
        report = test_report.attach(state, context.session_key, run_contract.current(state, context.session_key),
                                    hook_input, run_contract.project_root(str(hook_input.get("cwd") or "")))
    except Exception:  # noqa: BLE001 - without the report the server reads the command's output
        report = None
    return {**hook_input, run_contract.FACTS_KEY: {"test_report": report}} if report else hook_input


def _remember(state: LocalState, context: SessionContext, result: PlatformResult) -> dict[str, Any] | None:
    try:
        return run_contract.remember(state, context.session_key, result.body if result.outcome == "ok" else None)
    except Exception:  # noqa: BLE001 - remembering is best effort
        return None
