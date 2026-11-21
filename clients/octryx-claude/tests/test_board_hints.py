"""S4: the Stop-hook handoff nudge (once per change, never a loop) and the takeover-decision guard."""

from __future__ import annotations

import io
import json

import httpx

from octryx_claude import board_hints, hooks, pre_tool_use_hook
from octryx_claude.platform import PlatformResult
from tests.hooks_support import KEY

from .conftest import BASE_URL

LINE = "Update the handoff for BRD-6 with work_item_handoff_write before stopping."


def _verified(nudges, **extra) -> PlatformResult:
    return PlatformResult("ok", body={"state": "passed", "handoff_nudges": nudges, **extra}, status_code=200,
                          state="passed")


def test_the_nudge_blocks_once_per_change():
    first = _verified([{"work_item_key": "BRD-6", "marker": "c1:-:0"}])
    output, nudged = board_hints.with_handoff_nudge(None, first, nudged=[])
    assert output == {"decision": "block", "reason": LINE} and nudged == ["c1:-:0"]
    assert board_hints.with_handoff_nudge(None, first, nudged=nudged) == (None, nudged)  # same change: no block
    changed = _verified([{"work_item_key": "BRD-6", "marker": "c1:2026-10-06T10:00:00Z:1"}])
    output, nudged = board_hints.with_handoff_nudge(None, changed, nudged=nudged)
    assert output == {"decision": "block", "reason": LINE} and len(nudged) == 2


def test_the_nudge_never_loops_and_ignores_malformed_entries():
    nudges = _verified([{"work_item_key": "BRD-6", "marker": "c1:-:0"}])
    nudged, blocks = [], 0
    for _stop in range(10):  # an agent that never writes the handoff
        output, nudged = board_hints.with_handoff_nudge(None, nudges, nudged=nudged)
        blocks += 1 if output else 0
    assert blocks == 1
    for quiet in (_verified([]), _verified(None), _verified([{"work_item_key": "K", "marker": "bad marker!"}]),
                  _verified([{"work_item_key": "<b>", "marker": "m"}]), _verified(["x"]),
                  PlatformResult("refused", body={"handoff_nudges": [{"work_item_key": "K", "marker": "m"}]})):
        assert board_hints.with_handoff_nudge(None, quiet, nudged=[]) == (None, [])
    many = [f"m{n}" for n in range(60)]
    _, kept = board_hints.with_handoff_nudge(None, _verified([{"work_item_key": "BRD-7", "marker": "new"}]),
                                             nudged=many)
    assert len(kept) == board_hints.MAX_REMEMBERED_MARKERS and kept[-1] == "new"


def test_the_nudge_joins_other_outputs_and_names_every_item():
    nudges = _verified([{"work_item_key": "BRD-7", "marker": "b"}, {"work_item_key": "BRD-6", "marker": "a"}])
    output, _ = board_hints.with_handoff_nudge({"decision": "block", "reason": "Run the tests."}, nudges, nudged=[])
    assert output == {"decision": "block", "reason": "Run the tests.\nUpdate the handoff for BRD-6, BRD-7 with "
                                                     "work_item_handoff_write before stopping."}
    output, _ = board_hints.with_handoff_nudge({"systemMessage": "not configured"}, nudges, nudged=["a"])
    assert output == {"decision": "block", "systemMessage": "not configured",
                      "reason": "Update the handoff for BRD-7 with work_item_handoff_write before stopping."}


def test_the_stop_runner_nudges_once_then_lets_the_agent_stop(state, monkeypatch, capsys):
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    answer = _verified([{"work_item_key": "BRD-6", "marker": "c1:-:0"}], unread_for_me=0)
    monkeypatch.setattr(hooks, "call_control_plane", lambda *args, **kwargs: answer)
    outputs = []
    for active in (False, True):
        hook_input = {"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": active}
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
        assert hooks.run_stop(state, httpx.Client()) == 0
        outputs.append(capsys.readouterr().out)
    assert json.loads(outputs[0]) == {"decision": "block", "reason": LINE}
    assert outputs[1] == ""


def test_a_bash_call_to_a_takeover_decision_is_denied_locally(state, monkeypatch, capsys):
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    calls = []
    monkeypatch.setattr(pre_tool_use_hook, "call_control_plane", lambda *args, **kwargs: calls.append(1)
                        or PlatformResult("ok", body={"decision": "allow"}, status_code=200))
    for command, denied in (
        ("curl -X POST https://octryx.example/api/v1/agent-board/takeovers/abc-1/confirm", True),
        ("curl -XPOST 'https://octryx.example/api/v1/agent-board/takeovers/abc/DECLINE'", True),
        ("curl https://octryx.example/api/v1/agent-board/takeovers?project_id=x", False),
        ("git status", False),
    ):
        hook_input = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
        assert pre_tool_use_hook.run_pre_tool_use(state, httpx.Client()) == 0
        out = capsys.readouterr().out
        if denied:
            decision = json.loads(out)["hookSpecificOutput"]
            assert decision["permissionDecision"] == "deny" and "Octryx UI" in decision[
                "permissionDecisionReason"]
        else:
            assert out == ""
    assert len(calls) == 2  # denied calls never reach the platform
    assert not board_hints.calls_takeover_decision("Read", {"command": "agent-board/takeovers/x/confirm"})


def test_an_offer_nudges_once_with_its_own_line():
    """judge-s4 F1: an offered agent is told once; it decides itself whether to request the item."""
    offer = _verified([{"work_item_key": "BRD-6", "marker": "offer:c1:2026-10-06T10:00:00Z", "kind": "offer"},
                       {"work_item_key": "BRD-7", "marker": "c2:-:0", "kind": "update"}])
    output, nudged = board_hints.with_handoff_nudge(None, offer, nudged=[])
    assert output == {"decision": "block", "reason": LINE.replace("BRD-6", "BRD-7") + "\n" + board_hints.offer_line(
        ["BRD-6"])}
    assert "work_item_takeover_request" in board_hints.offer_line(["BRD-6"])
    assert board_hints.with_handoff_nudge(None, offer, nudged=nudged) == (None, nudged)
