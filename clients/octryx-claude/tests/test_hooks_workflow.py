"""The workflow confirm and decide proofs, and the board reminder that blocks a stop once per new unread count."""

from __future__ import annotations

import hashlib
import hmac
import io
import json

import httpx

from octryx_claude import hooks, pre_tool_use_hook, signer, stop_outputs
from octryx_claude.platform import PlatformResult
from tests.hooks_support import KEY, _ok

from .conftest import BASE_URL


def _confirm_input(monkeypatch) -> dict:
    hook_input = {"hook_event_name": "PreToolUse", "tool_name": pre_tool_use_hook.WORKFLOW_CONFIRM_TOOL,
                  "tool_use_id": "toolu_01AbC", "tool_input": {"approval_id": "3f2a-77"}}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    return hook_input


LINE = "unread board messages for you. Read them with board_read, then continue or stop."


def _passed(count) -> PlatformResult:
    return _ok({"state": "passed", "unread_for_me": count})


def test_workflow_confirm_sends_a_signed_proof_and_fails_closed_without_the_signer(short_state, monkeypatch, capsys):
    hook_key = b"s" * 32
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"decision": "ask", "state": "needs_confirmation",
                                         "confirmation_ticket": "tkt_1"})

    hook_input = _confirm_input(monkeypatch)
    with signer.start_signer(short_state, KEY, hook_key):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert pre_tool_use_hook.run_pre_tool_use(short_state, client) == 0
    [body] = bodies
    proof = body.pop("confirmation_proof")
    assert body == hook_input
    message = signer.confirm_message(KEY, "toolu_01AbC", "3f2a-77", proof["nonce"], proof["ts"])
    assert proof["mac"] == hmac.new(hook_key, message.encode(), hashlib.sha256).hexdigest()
    output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert output["updatedInput"] == {"approval_id": "3f2a-77", "confirmation_ticket": "tkt_1"}

    _confirm_input(monkeypatch)  # the signer is down now
    assert pre_tool_use_hook.run_pre_tool_use(short_state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    denied = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert denied["permissionDecision"] == "deny"
    assert denied["permissionDecisionReason"] == pre_tool_use_hook.PROOF_UNAVAILABLE_REASON
    assert len(bodies) == 1  # no tool-check without a proof


def test_the_board_reminder_blocks_once_per_new_unread_count():
    blocked, remembered = hooks.with_board_reminder(None, _passed(3), reminded=0)
    assert blocked == {"decision": "block", "reason": f"3 {LINE}"} and remembered == 3
    # The same count never blocks again: the next stop goes through.
    assert hooks.with_board_reminder(None, _passed(3), reminded=remembered) == (None, 3)
    # board_ack lowers the count: no block, and the lower count is remembered ...
    assert hooks.with_board_reminder(None, _passed(1), reminded=3) == (None, 1)
    # ... so a new message (a rise) blocks once more.
    again, remembered = hooks.with_board_reminder(None, _passed(2), reminded=1)
    assert again == {"decision": "block", "reason": f"2 {LINE}"} and remembered == 2
    assert hooks.with_board_reminder(None, _passed(0), reminded=2) == (None, 0)
    assert stop_outputs.board_reminder(1) == (
        "1 unread board message for you. Read it with board_read, then continue or stop.")


def test_the_board_reminder_never_loops_and_never_shows_bodies():
    remembered, blocks = 0, 0
    for _stop in range(10):  # an agent that never reads the board
        output, remembered = hooks.with_board_reminder(None, _passed(4), reminded=remembered)
        blocks += 1 if output else 0
    assert blocks == 1
    for quiet in (_ok({"state": "passed"}), _passed("5"), _passed(-1), PlatformResult("unreachable"),
                  PlatformResult("refused", body={"unread_for_me": 2})):
        assert hooks.with_board_reminder(None, quiet, reminded=7) == (None, 7)


def test_the_board_reminder_joins_verification_outputs():
    blocked = _ok({"state": "blocked", "detail": "Run the focused tests.", "unread_for_me": 2})
    gate, _ = hooks.stop_output(blocked, stop_hook_active=False, prior_blocks=0)
    output, remembered = hooks.with_board_reminder(gate, blocked, reminded=2)
    assert output == {"decision": "block", "reason": f"Run the focused tests.\n2 {LINE}"} and remembered == 2
    configured = _ok({"state": "needs_configuration", "unread_for_me": 2})
    warning, _ = hooks.stop_output(configured, stop_hook_active=False, prior_blocks=0)
    output, _ = hooks.with_board_reminder(warning, configured, reminded=0)
    assert output["decision"] == "block" and output["reason"] == f"2 {LINE}"
    assert output["systemMessage"] == warning["systemMessage"]
    assert hooks.with_board_reminder(warning, configured, reminded=2) == (warning, 2)


def test_the_stop_runner_blocks_once_then_lets_the_agent_stop(state, monkeypatch, capsys):
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setattr(hooks, "call_control_plane", lambda *args, **kwargs: _passed(4))
    outputs = []
    for active in (False, True):
        hook_input = {"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": active}
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
        assert hooks.run_stop(state, httpx.Client()) == 0
        outputs.append(capsys.readouterr().out)
    assert json.loads(outputs[0]) == {"decision": "block", "reason": f"4 {LINE}"}
    assert outputs[1] == ""


def test_workflow_decide_sends_a_decide_proof_over_the_run_and_shows_the_exact_payload(short_state, monkeypatch,
                                                                                    capsys):
    hook_key = b"d" * 32
    run_id = "3f2a9c1e-5b4d-4e6f-8a7b-9c0d1e2f3a4b"
    payload = "Payload sha256:" + "a" * 64 + ": " + json.dumps({"criteria": ["x" * 50] * 20})
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"decision": "ask", "reason": "workflow_decision_confirmation",
                                         "message": payload, "confirmation_ticket": "tkt_2"})

    tool_input = {"run_id": run_id, "action": "confirm", "payload_hash": "sha256:" + "a" * 64}
    hook_input = {"hook_event_name": "PreToolUse", "tool_name": pre_tool_use_hook.WORKFLOW_DECIDE_TOOL,
                  "tool_use_id": "toolu_02", "tool_input": tool_input}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    with signer.start_signer(short_state, KEY, hook_key):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert pre_tool_use_hook.run_pre_tool_use(short_state, client) == 0
    proof = bodies[0]["confirmation_proof"]
    message = signer.confirm_message(KEY, "toolu_02", run_id, proof["nonce"], proof["ts"], "decide")
    assert proof["mac"] == hmac.new(hook_key, message.encode(), hashlib.sha256).hexdigest()
    output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert output["permissionDecision"] == "ask" and output["permissionDecisionReason"] == payload  # not cut at 600
    assert output["updatedInput"] == {**tool_input, "confirmation_ticket": "tkt_2"}

    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    assert pre_tool_use_hook.run_pre_tool_use(short_state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"  # no signer
    assert len(bodies) == 1
