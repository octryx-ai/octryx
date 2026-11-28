"""The PostToolUse hook command: reports that a tool ran and relays a changed run contract.
Observational: prints context only, never blocks."""

from __future__ import annotations

import httpx

from octryx_claude import contract_notices, local_tests_screens

from . import codex_hook_input, hook_timings, local_decisions, local_tests, pipeline, run_contract
from .content_hooks import content_output
from .handoff_hooks import auto_handoff, with_notice
from .hook_evidence import MAX_TEST_BRIEF, _remember, _route_notice, _with_test_report, launcher_texts
from .hook_outputs import _emit, _read_hook_input, _with_context, unwrapped
from .platform import SessionContext, call_control_plane
from .state import LocalState

TOOL_EXECUTED_TIMEOUT = 4.0
_TOOL_EXECUTED_EVENTS = {"PostToolUse", "PostToolUseFailure"}


def run_post_tool_use(state: LocalState, http: httpx.Client) -> int:
    try:
        raw = _read_hook_input()
        # A browser that could not start inside the sandbox: the model hears what runs instead (``local_tests``).
        hook_input = unwrapped(raw)
        context = SessionContext.from_env()
        note = pipeline.text(launcher_texts(state, context), "run.launcher.sandbox_browser") \
            if local_tests_screens.sandbox_browser_failure(raw) else ""
        if not note and context is not None:  # a style tool that could not run in the sandbox: say so
            tool = local_tests_screens.sandbox_tool_failure(raw, local_tests.style_tools(
                run_contract.current(state, context.session_key)))
            texts = launcher_texts(state, context)
            note = pipeline.text(texts, "run.launcher.compound_tool", tool=tool) if tool else ""
        if context is None or str(hook_input.get("hook_event_name") or "") not in _TOOL_EXECUTED_EVENTS:
            return 0
        folder = state.session_dir(context.session_key)
        parts = codex_hook_input.split_apply_patch(hook_input)  # a Codex patch: the evidence of every file it changed
        if local_decisions.load_policy(folder) is not None and not str(parts[0].get("tool_name") or "").startswith(
                "mcp__octryx-knowledge__"):
            # A session that decides locally: the evidence goes with the next batch (never a wait per tool call).
            for part in parts:
                local_decisions.spool(folder, "post", _with_test_report(state, context, part))
            _emit(_with_context(None, "PostToolUse", note))
            return 0
        for part in parts[:-1]:
            call_control_plane(state, context, "POST", "/sessions/tool-executed", http=http,
                               timeout=TOOL_EXECUTED_TIMEOUT, body=_with_test_report(state, context, part))
        hook_input = parts[-1]
        result = call_control_plane(
            state, context, "POST", "/sessions/tool-executed",
            http=http, timeout=TOOL_EXECUTED_TIMEOUT, body=_with_test_report(state, context, hook_input),
        )
        hook_timings.mark("reported", tool=hook_input.get("tool_name") or "")
        body = result.body if result.outcome == "ok" else {}
        output = _with_context(content_output(body, str(hook_input.get("tool_name") or "")),  # Content policy
                               "PostToolUse", note)
        # A long test run's summary and failures, which the agent cannot read in Claude Code's file.
        output = _with_context(output, "PostToolUse", str(body.get("test_brief") or "")[:MAX_TEST_BRIEF])
        # A changed run contract (a new phase, a pause, a waiting decision) reaches the model and the user once.
        contract = _remember(state, context, result)
        changed = contract_notices.changed_notice(state, context.session_key, contract)
        output = with_notice(_with_context(output, "PostToolUse", changed), changed)
        # A new phase agent's instructions reach the model once.
        notice = contract_notices.agent_notice(state, context.session_key, contract) if contract else ""
        output = _with_context(output, "PostToolUse", notice)
        output = with_notice(output, _route_notice(state, context, result))
        _emit(with_notice(output, auto_handoff(state, context, http, result, hook_input.get("cwd") or ".")))
        hook_timings.mark("emitted")
    except Exception:  # noqa: BLE001 - evidence is best effort; never disturb the tool flow
        pass
    return 0
