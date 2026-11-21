"""Hook output mapping for every control-plane state, incl. the stop-block cap."""

from __future__ import annotations

from octryx_claude import hook_outputs, hooks
from octryx_claude.platform import PlatformResult
from tests.hooks_support import _decision, _ok


def test_pre_tool_use_allow_defers_to_the_normal_permission_flow():
    assert hook_outputs.pre_tool_use_output(_ok({"decision": "allow", "state": "allowed"})) is None


def test_an_allow_the_platform_rewrote_runs_rewritten_in_claude_code_and_unchanged_in_codex(monkeypatch):
    """The platform may give a pytest run ``-v`` (``updated_input``); Codex has no updatedInput."""
    tool_input = {"command": "python -m pytest -q"}
    answer = _ok({"decision": "allow", "updated_input": {"command": "python -m pytest -q -v"}})
    monkeypatch.delenv("OCTRYX_ENGINE", raising=False)
    output = hook_outputs.pre_tool_use_output(answer, tool_input)["hookSpecificOutput"]
    assert output["permissionDecision"] == "allow" and output["updatedInput"] == {"command": "python -m pytest -q -v"}
    monkeypatch.setenv("OCTRYX_ENGINE", "codex")
    assert hook_outputs.pre_tool_use_output(answer, tool_input) is None


def test_pre_tool_use_deny_and_every_failure_deny():
    denied = hook_outputs.pre_tool_use_output(
        _ok({"decision": "deny", "state": "denied", "reason": "command_prefix_denied", "rule_id": "no-push-to-main"})
    )
    assert _decision(denied) == "deny"
    assert denied["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "[rule no-push-to-main]" in denied["hookSpecificOutput"]["permissionDecisionReason"]

    for failure in (
        PlatformResult("unreachable", reason="platform_unreachable"),
        PlatformResult("refused", status_code=403, state="denied", reason="workspace_not_authorized"),
        _ok({"decision": "maybe"}),
    ):
        output = hook_outputs.pre_tool_use_output(failure)
        assert _decision(output) == "deny"
        assert "fail closed" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_pre_tool_use_ask_hands_the_confirmation_to_the_claude_code_prompt():
    asked = hook_outputs.pre_tool_use_output(
        _ok({"decision": "ask", "state": "needs_confirmation", "reason": "workflow_confirmation_required",
             "rule_id": None, "message": "Confirm approval\x07 of workflow release-1."})
    )
    assert asked == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                            "permissionDecisionReason": "Confirm approval  of workflow release-1."}}
    for message in (None, "", "   "):
        answer = _ok({"decision": "ask", "state": "needs_confirmation", "message": message})
        output = hook_outputs.pre_tool_use_output(answer)
        assert _decision(output) == "ask"
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == hook_outputs.ASK_DEFAULT_REASON
    long_ask = hook_outputs.pre_tool_use_output(_ok({"decision": "ask", "message": "x" * 5000}))
    assert len(long_ask["hookSpecificOutput"]["permissionDecisionReason"]) == hook_outputs.MAX_MESSAGE_CHARS


def test_stop_blocks_until_the_cap_then_allows_with_a_system_message():
    blocked = _ok({"state": "blocked", "reason": "tests_not_run", "detail": "Run the focused tests."})

    output, count = hooks.stop_output(blocked, stop_hook_active=False, prior_blocks=0)
    assert output == {"decision": "block", "reason": "Run the focused tests."} and count == 1
    output, count = hooks.stop_output(blocked, stop_hook_active=True, prior_blocks=count)
    assert output["decision"] == "block" and count == 2
    output, count = hooks.stop_output(blocked, stop_hook_active=True, prior_blocks=count)
    assert output["decision"] == "block" and count == 3
    output, count = hooks.stop_output(blocked, stop_hook_active=True, prior_blocks=count)
    assert "decision" not in output and "still red" in output["systemMessage"] and count == 0
    # A new stop chain (stop_hook_active false) is gated again from zero.
    output, count = hooks.stop_output(blocked, stop_hook_active=False, prior_blocks=3)
    assert output["decision"] == "block" and count == 1


def test_stop_allows_passed_and_warns_for_configuration_or_outage():
    assert hooks.stop_output(_ok({"state": "passed"}), stop_hook_active=True, prior_blocks=2) == (None, 0)
    assert hooks.stop_output(_ok({"state": "not_applicable"}), stop_hook_active=False, prior_blocks=0) == (None, 0)
    for result in (
        _ok({"state": "needs_configuration", "reason": "verification_not_configured"}),
        PlatformResult("unreachable", reason="platform_unreachable"),
    ):
        output, count = hooks.stop_output(result, stop_hook_active=False, prior_blocks=0)
        assert set(output) == {"systemMessage"} and count == 0


def test_pre_tool_use_deny_shows_the_platform_message_after_rule_and_code():
    denied = hook_outputs.pre_tool_use_output(_ok({
        "decision": "deny", "state": "denied", "reason": "capability_read_only", "rule_id": "capability-gate",
        "message": "Edits need a change workflow\x1b; ask to confirm a change workflow",
    }))
    assert denied["hookSpecificOutput"]["permissionDecisionReason"] == (
        "Octryx policy denied this tool call [rule capability-gate] (capability_read_only): "
        "Edits need a change workflow ; ask to confirm a change workflow")


def test_ask_with_a_ticket_passes_it_into_the_mcp_call_only_when_valid():
    tool_input = {"approval_id": "3f2a-77", "note": "go"}
    asked = hook_outputs.pre_tool_use_output(
        _ok({"decision": "ask", "message": "Confirm release-1.", "confirmation_ticket": "tkt_AbC-123"}), tool_input)
    assert asked["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "Confirm release-1.",
        "updatedInput": {"approval_id": "3f2a-77", "note": "go", "confirmation_ticket": "tkt_AbC-123"},
    }
    for ticket in ("bad ticket", "x" * 129, 42, ""):
        plain = hook_outputs.pre_tool_use_output(_ok({"decision": "ask", "confirmation_ticket": ticket}), tool_input)
        assert "updatedInput" not in plain["hookSpecificOutput"] and _decision(plain) == "ask"
