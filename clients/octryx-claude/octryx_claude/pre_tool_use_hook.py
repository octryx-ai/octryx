"""The PreToolUse hook command (``hooks.run_pre_tool_use``): the platform decides (``POST /sessions/tool-check``),
fail closed; a session that decides on the device decides the hard-deny list itself (``local_decisions``)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from octryx_claude import browser_rules, local_tests_words, pipeline_texts

from . import (
    codex_hook_input,
    hook_timings,
    local_decisions,
    pipeline,
    run_contract,
    spill_copy,
)
from .board_hints import calls_takeover_decision
from .hook_evidence import _note_system_test_run, _note_test_report, _remember, _with_facts, launcher_texts
from .hook_outputs import (
    _allows,
    _deny,
    _emit,
    _read_hook_input,
    _redirected_output,
    pre_tool_use_output,
    test_run_output,
)
from .launch_sandbox import TEST_RUN_SHIM_ENV
from .platform import PlatformResult, SessionContext, call_control_plane
from .signer import confirmation_proof
from .state import LocalState

PRE_TOOL_USE_TIMEOUT = 8.0


WORKFLOW_CONFIRM_TOOL = "mcp__octryx-knowledge__workflow_confirm"
WORKFLOW_DECIDE_TOOL = "mcp__octryx-knowledge__workflow_decide"
_PROVED_TOOLS = {WORKFLOW_CONFIRM_TOOL: ("confirm", "approval_id"), WORKFLOW_DECIDE_TOOL: ("decide", "run_id")}
PROOF_UNAVAILABLE_REASON = pipeline_texts.FALLBACK_TEXTS["run.launcher.proof_unavailable"]  # the platform's text wins


def _local_deny(state: LocalState, context: SessionContext, hook_input: dict[str, Any], code: str,
                message: str) -> dict[str, Any]:
    try:
        local_decisions.spool(state.session_dir(context.session_key), "pre", hook_input,
                              decision=local_decisions.DENY, reason=code, message=message)
    except OSError:
        pass  # the denial itself must not depend on the audit
    return _deny(message)


def _local_pre_tool_use(state: LocalState, context: SessionContext,
                        hook_input: dict[str, Any]) -> dict[str, Any] | None:
    folder = state.session_dir(context.session_key)
    policy = local_decisions.load_policy(folder)
    if policy is None:
        return None
    contract = run_contract.current(state, context.session_key)
    verdict, reason, message = local_decisions.decide(hook_input, policy, contract)
    if verdict == local_decisions.SERVER:
        return None
    if verdict == local_decisions.DENY:
        local_decisions.spool(folder, "pre", hook_input, decision=verdict, reason=reason, message=message)
        return local_decisions.deny_output(reason, message)
    _note_test_report(state, context, hook_input)
    _note_system_test_run(state, context, hook_input)
    return test_run_output(hook_input, contract, os.environ.get(TEST_RUN_SHIM_ENV, "")) or {}


def run_pre_tool_use(state: LocalState, http: httpx.Client) -> int:
    try:
        hook_input = _read_hook_input()
        context = SessionContext.from_env()
        if context is None or not hook_input:
            _emit(pre_tool_use_output(PlatformResult("unreachable", reason="hook_context_missing")))
            return 0
        # A Codex patch is decided per file (``codex_hook_input``): the first denial is the answer.
        output: dict[str, Any] | None = None
        if codex_hook_input.unreadable_patch(hook_input):  # a broken patch: how to write one, not "unclassified"
            _emit(_local_deny(state, context, hook_input, "local_unreadable_patch",
                              pipeline.text(launcher_texts(state, context), "run.launcher.patch_format")))
            return 0
        for part in codex_hook_input.split_apply_patch(hook_input):
            output = _pre_tool_use_decision(state, http, context, part)
            if codex_hook_input.in_codex():
                output = codex_hook_input.without_ask(output)  # Codex cannot ask: an ask is a deny there
            if codex_hook_input.is_deny(output):
                break
        hook_timings.mark("decided", tool=hook_input.get("tool_name") or "")
        _emit(codex_hook_input.decided(output) if codex_hook_input.guarded() else output)
    except Exception:  # noqa: BLE001 - any internal failure must still deny
        _emit(pre_tool_use_output(PlatformResult("unreachable", reason="hook_internal_error")))
    return 0


def browser_refusal(hook_input: dict[str, Any]) -> dict[str, Any] | None:
    name = str(hook_input.get("tool_name") or "")
    if not name.startswith(browser_rules.BROWSER_TOOL_PREFIX):
        return None
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    refused = browser_rules.browser_rule(name, tool_input)
    return local_decisions.deny_output(*refused) if refused is not None else None


def _pre_tool_use_decision(state: LocalState, http: httpx.Client, context: SessionContext,
                           hook_input: dict[str, Any]) -> dict[str, Any] | None:
    redirected = spill_copy.redirect(state, context.session_key, hook_input)
    if redirected is not None:  # the session's own spilled tool output, read from a copy (``spill_copy``)
        hook_input = {**hook_input, "tool_input": redirected}
    output = _decided(state, http, context, hook_input)
    return _redirected_output(output, redirected) if redirected is not None else output


def _decided(state: LocalState, http: httpx.Client, context: SessionContext,
             hook_input: dict[str, Any]) -> dict[str, Any] | None:
    tool_input = hook_input.get("tool_input")
    if calls_takeover_decision(hook_input.get("tool_name"), tool_input):
        # a person decides in the UI, never the agent
        return _local_deny(state, context, hook_input, "local_takeover_decision",
                           pipeline.text(launcher_texts(state, context), "run.launcher.takeover_denied"))
    if hook_input.get("tool_name") == "Bash" and isinstance(tool_input, dict) and local_tests_words.names_wrapper(
            str(tool_input.get("command") or "")):
        return _local_deny(state, context, hook_input, "local_test_run_wrapper",
                           pipeline.text(launcher_texts(state, context), "run.launcher.wrapper_denied"))
    local = _local_pre_tool_use(state, context, hook_input)
    if local is not None:
        return local or None
    body = _with_facts(state, context, hook_input, with_diff=False)
    _note_test_report(state, context, hook_input)
    _note_system_test_run(state, context, hook_input)
    if hook_input.get("tool_name") in _PROVED_TOOLS:
        # A confirmation (approval id) or a run decision (run id): the user answers in the permission prompt.
        verb, field = _PROVED_TOOLS[hook_input["tool_name"]]
        bound_id = tool_input.get(field) if isinstance(tool_input, dict) else None
        proof = confirmation_proof(state, context.session_key, hook_input.get("tool_use_id"), bound_id, verb)
        if proof is None:
            return _local_deny(state, context, hook_input, "local_proof_unavailable",
                               pipeline.text(launcher_texts(state, context), "run.launcher.proof_unavailable"))
        body = {**body, "confirmation_proof": proof}
    result = call_control_plane(
        state, context, "POST", "/sessions/tool-check",
        http=http, timeout=PRE_TOOL_USE_TIMEOUT, body=body, retry=True,
    )
    contract = _remember(state, context, result) or run_contract.current(state, context.session_key)
    output = pre_tool_use_output(result, tool_input, dict((contract or {}).get("prompt_texts") or {})
                                 if isinstance(contract, dict) else None)
    if not codex_hook_input.is_deny(output) and (refused := browser_refusal(hook_input)) is not None:
        # the platform recorded the call as allowed; the device's own browser rule is stricter (its port)
        reason = str(refused.get("hookSpecificOutput", {}).get("permissionDecisionReason") or "")
        return _local_deny(state, context, hook_input, "local_browser_rule", reason)
    updated = (output or {}).get("hookSpecificOutput", {}).get("updatedInput") if _allows(output) else None
    if output is None or updated is not None:
        # A test run the platform rewrote is wrapped as rewritten.
        wrapped = test_run_output({**hook_input, "tool_input": updated} if updated else hook_input, contract,
                                  os.environ.get(TEST_RUN_SHIM_ENV, ""))
        output = wrapped or output
    return output
