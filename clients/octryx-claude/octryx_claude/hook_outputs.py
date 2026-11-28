"""Hook stdout builders and hook I/O shared by the hook commands (``hooks``): the PreToolUse permission answers, a
test run wrapped to run outside the sandbox, context for the model, and reading and writing the hook's JSON."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from octryx_claude import local_tests_forms, local_tests_words, pipeline_texts

from . import codex_hook_input, local_tests, pipeline
from .platform import PlatformResult, safe_code

MAX_HOOK_INPUT_BYTES = 4 * 1024 * 1024
MAX_MESSAGE_CHARS = 600
MAX_ASK_CHARS = 2600

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_RULE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TICKET = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _bounded_text(value: object, limit: int = MAX_MESSAGE_CHARS) -> str:
    text = _CONTROL.sub(" ", str(value or "")).strip()
    return text[:limit]


def _codes(result: PlatformResult) -> str:
    parts = [part for part in (result.state, result.reason) if part]
    return f" ({'/'.join(parts)})" if parts else ""


ASK_DEFAULT_REASON = "Octryx asks you to confirm this action."


def _permission(decision: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


def _deny(reason: str) -> dict[str, Any]:
    return _permission("deny", reason)


def _ask(body: dict[str, Any], tool_input: object) -> dict[str, Any]:
    # A run decision's prompt shows its exact payload, so it may be longer than a policy message.
    limit = MAX_ASK_CHARS if body.get("reason") == "workflow_decision_confirmation" else MAX_MESSAGE_CHARS
    output = _permission("ask", _bounded_text(body.get("message"), limit) or ASK_DEFAULT_REASON)
    ticket = body.get("confirmation_ticket")
    if isinstance(ticket, str) and _TICKET.match(ticket) and isinstance(tool_input, dict):
        # Only the real MCP call carries the one-time ticket.
        output["hookSpecificOutput"]["updatedInput"] = {**tool_input, "confirmation_ticket": ticket}
    return output


def _deny_detail(body: dict[str, Any]) -> str:
    rule = str(body.get("rule_id") or "")
    label = f" [rule {rule}]" if _RULE_ID.match(rule) else ""
    code = safe_code(body.get("reason"))
    message = _bounded_text(body.get("message"))
    detail = f"{label}{f' ({code})' if code else ''}"
    return f"Octryx policy denied this tool call{detail}: {message or 'not allowed'}"


WRAPPER_DENY_REASON = pipeline_texts.FALLBACK_TEXTS["run.launcher.wrapper_denied"]


# A test run written to a file runs inside the sandbox, where Chromium cannot start: the session hears the form
# that runs outside.
PLAIN_FORM_REASON = pipeline_texts.FALLBACK_TEXTS["run.launcher.plain_form"]


def test_run_output(hook_input: dict[str, Any], contract: dict[str, Any] | None,
                    shim: str = "") -> dict[str, Any] | None:
    tool_input = hook_input.get("tool_input")
    if hook_input.get("tool_name") != "Bash" or not isinstance(tool_input, dict) or not shim:
        return None
    if not isinstance(contract, dict) or not contract.get("phase"):
        return None
    command = str(tool_input.get("command") or "")
    root = str(hook_input.get("cwd") or "")
    pinned = contract.get("environment_pin") if isinstance(contract.get("environment_pin"), dict) else None
    tools = local_tests.style_tools(contract)  # the platform's style check, run the same way and place
    if not local_tests.is_test_run(command, root, pinned, tools):
        plain = local_tests_forms.plain_form(command, root)
        texts = dict(contract.get("prompt_texts") or {})
        if plain:
            return _deny(pipeline.text(texts, "run.launcher.plain_form", plain=plain))
        system = local_tests_forms.compound_system_test(command, root, pinned)
        # The system test among other commands: inside the sandbox its browser never starts.
        if system:
            return _deny(pipeline.text(texts, "run.launcher.compound_test", command=system))
        tool = local_tests_forms.compound_style_tool(command, root, tools)
        # A style tool that cannot run in the sandbox among other commands: it would fail silently.
        return _deny(pipeline.text(texts, "run.launcher.compound_tool", tool=tool)) if tool else None
    output = _permission("allow", "a test run: it starts the app and the device's browser outside the sandbox")
    output["hookSpecificOutput"]["updatedInput"] = {**tool_input, "command": local_tests_words.wrap(shim, command)}
    return output


def unwrapped(hook_input: dict[str, Any]) -> dict[str, Any]:
    tool_input = hook_input.get("tool_input")
    if hook_input.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
        return hook_input
    original = local_tests.unwrap(str(tool_input.get("command") or ""))
    if original is None:
        return hook_input
    return {**hook_input, "tool_input": {**tool_input, "command": original}}


def _rewritten(body: dict[str, Any], tool_input: object) -> dict[str, Any] | None:
    updated = body.get("updated_input")
    if not isinstance(updated, dict) or not isinstance(tool_input, dict) or codex_hook_input.in_codex():
        return None
    output = _permission("allow", _bounded_text(body.get("message")) or "Octryx adjusted this tool call.")
    output["hookSpecificOutput"]["updatedInput"] = updated
    return output


def pre_tool_use_output(result: PlatformResult, tool_input: object = None,
                        texts: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if result.outcome == "ok":
        decision = result.body.get("decision")
        if decision == "allow":
            return _rewritten(result.body, tool_input)
        if decision == "ask":
            return _ask(result.body, tool_input)
        if decision == "deny":
            return _deny(_deny_detail(result.body))
    return _deny(pipeline.text(texts, "run.launcher.fail_closed", codes=_codes(result)))


def _read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_HOOK_INPUT_BYTES + 1)
    if len(raw) > MAX_HOOK_INPUT_BYTES:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _with_context(output: dict[str, Any] | None, event: str, text: str) -> dict[str, Any] | None:
    if not text:
        return output
    specific = dict((output or {}).get("hookSpecificOutput") or {})
    previous = str(specific.get("additionalContext") or "")
    specific.update(hookEventName=event, additionalContext=f"{previous}\n{text}".strip())
    return {**(output or {}), "hookSpecificOutput": specific}


def _emit(output: dict[str, Any] | None) -> None:
    if output is not None:
        sys.stdout.write(json.dumps(output))
        sys.stdout.flush()


def _redirected_output(output: dict[str, Any] | None, redirected: dict[str, Any]) -> dict[str, Any] | None:
    if output is None:
        output = _permission("allow", "the session's own tool output, read from a copy")
    specific = output.get("hookSpecificOutput")
    if not isinstance(specific, dict) or specific.get("permissionDecision") == "deny":
        return output
    specific["updatedInput"] = {**redirected, **dict(specific.get("updatedInput") or {})}
    return output


def _allows(output: dict[str, Any] | None) -> bool:
    specific = (output or {}).get("hookSpecificOutput")
    return isinstance(specific, dict) and specific.get("permissionDecision") == "allow"
