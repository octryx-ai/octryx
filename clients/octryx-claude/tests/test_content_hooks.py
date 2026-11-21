"""PostToolUse shows what a content policy did with a tool's output — counts only, never the data."""

from __future__ import annotations

import io
import json

import httpx

from octryx_claude import post_tool_use_hook
from octryx_claude.content_hooks import (
    BLOCKED_NOTE,
    KEPT_NOTE,
    MODEL_NOTE,
    WITHHELD_NOTE,
    content_output,
    route_message,
)
from octryx_claude.launch_settings import POST_TOOL_USE_MATCHER

BASE_URL = "https://platform.example"
KEY = ("1b4e" + "28ba-2fa1-11d2-883f-0016d3cca427")
MASKED = {"kind": "mask", "found": {"email": 14, "phone": 3}, "masked": 17,
          "policies": ["mask-personal-data-in-tool-results"], "decision_id": "d-1", "blocked": False}


def test_every_tool_is_reported_after_it_ran():
    assert POST_TOOL_USE_MATCHER == "*"


def test_a_masked_builtin_tool_gets_a_notice_and_a_model_note_only():
    output = content_output({"content": MASKED}, "Bash")
    assert output["systemMessage"] == ("Octryx: email ×14, phone ×3 masked "
                                       "(policy mask-personal-data-in-tool-results · decision d-1)")
    assert output["hookSpecificOutput"] == {"hookEventName": "PostToolUse", "additionalContext": MODEL_NOTE}


def test_an_output_the_client_keeps_claims_no_mask_block_or_withhold():
    for content in ({**MASKED, "kept_by_client": True}, {**MASKED, "blocked": False, "kind": "block",
                                                          "kept_by_client": True},
                    {"kind": "withhold", "found": {}, "withheld": 2, "kept_by_client": True, "blocked": False}):
        output = content_output({"content": content}, "Bash")
        assert output["hookSpecificOutput"] == {"hookEventName": "PostToolUse", "additionalContext": KEPT_NOTE}
        message = output["systemMessage"]
        assert "stays as it is" in message
        assert not any(word in message for word in ("masked", "kept out", "withheld"))


def test_an_mcp_tool_gets_the_masked_output_and_a_blocked_one_the_block_note():
    masked = content_output({"content": {**MASKED, "updated_output": [{"type": "text", "text": "[EMAIL #1]"}]}},
                            "mcp__logs__tail")
    assert masked["hookSpecificOutput"]["updatedMCPToolOutput"] == [{"type": "text", "text": "[EMAIL #1]"}]
    blocked = content_output({"content": {**MASKED, "blocked": True, "updated_output": "x"}}, "mcp__logs__tail")
    assert "updatedMCPToolOutput" not in blocked["hookSpecificOutput"]
    assert blocked["hookSpecificOutput"]["additionalContext"] == BLOCKED_NOTE
    assert "kept out of the model" in blocked["systemMessage"]
    builtin = content_output({"content": {**MASKED, "updated_output": "x"}}, "Bash")
    assert "updatedMCPToolOutput" not in builtin["hookSpecificOutput"]  # Claude Code replaces MCP output only
    assert content_output({"state": "recorded"}, "Bash") is None
    assert content_output({"content": {}}, "Bash") is None


def test_post_tool_use_emits_the_content_notice(state, monkeypatch, capsys):
    hook_input = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "toolu_02",
                  "tool_input": {"command": "kubectl logs pod"}, "tool_response": {"stdout": "synthetic"}}
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"state": "recorded", "reason": "execution_recorded_new_row",
                                         "content": MASKED})

    assert post_tool_use_hook.run_post_tool_use(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["systemMessage"].startswith("Octryx: email ×14")
    assert output["hookSpecificOutput"]["additionalContext"] == MODEL_NOTE


# --- the one-time terminal notice of a routed conversation -------------------------------------------------

HOSTILE = "4000123412341234"
ROUTE = {"route_to": "company-model", "categories": ["pii"], "detectors": {"email": 1, "phone": 1},
         "policy_id": "personal-data-approved-model", "decision_id": "7f21c0aa-1111-2222-3333-444455556666",
         "conversation": "c0ffee00-1111-2222-3333-444455556666", "since": "2026-10-07T09:14:02Z"}


def test_the_route_notice_names_the_model_the_reason_policy_and_decision():
    assert route_message(ROUTE, seat=True) == (
        "Octryx · This conversation now runs on company-model (governed) because it contained personal data "
        "(email ×1, phone ×1).\nPolicy: personal-data-approved-model · decision "
        "7f21c0aa-1111-2222-3333-444455556666\nMasked values are placeholders. Start a new conversation (/clear) to "
        "return to your seat model.")
    hostile = {**ROUTE, "route_to": HOSTILE, "detectors": {HOSTILE: 1}, "policy_id": f"x {HOSTILE}",
               "decision_id": HOSTILE}
    governed = route_message(hostile, seat=False)
    assert HOSTILE not in governed and "the approved model" in governed and "return to your model" in governed


def _run_post_tool_use(state, monkeypatch, capsys, answer: dict) -> dict | None:
    hook_input = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "toolu_03",
                  "session_id": ROUTE["conversation"], "tool_response": {"stdout": "ok"}}
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("OCTRYX_PROFILE", "seat")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=answer)))
    assert post_tool_use_hook.run_post_tool_use(state, client) == 0
    out = capsys.readouterr().out
    return json.loads(out) if out else None


def test_a_routed_conversation_is_announced_once_and_a_new_one_again(state, monkeypatch, capsys):
    answer = {"state": "recorded", "content_route": ROUTE}
    first = _run_post_tool_use(state, monkeypatch, capsys, answer)
    assert first["systemMessage"].startswith("Octryx · This conversation now runs on company-model")
    assert _run_post_tool_use(state, monkeypatch, capsys, answer) is None  # the same conversation: silent
    assert _run_post_tool_use(state, monkeypatch, capsys, {"state": "recorded"}) is None  # not routed: silent
    cleared = {"state": "recorded", "content_route": {**ROUTE, "conversation": "c0ffee00-9999-2222-3333-444455556666"}}
    assert "company-model" in _run_post_tool_use(state, monkeypatch, capsys, cleared)["systemMessage"]


# The platform's answer to ``POST /sessions/tool-executed`` for output it could not finish checking (the shape the
# backend test ``test_launcher_disposition_of_an_unfinished_result`` asserts for both delivery modes).
WITHHELD = {"kind": "withhold", "found": {}, "masked": 0, "withheld": 1, "policies": [], "decision_id": None,
            "reason": "content_scan_unfinished", "blocked": False,
            "updated_output": {"text": "[WITHHELD: content not fully scanned]"}}


def test_an_unfinished_result_is_withheld_for_mcp_and_explained_for_a_builtin_tool():
    mcp = content_output({"content": WITHHELD}, "mcp__logs__tail")
    assert mcp["hookSpecificOutput"]["updatedMCPToolOutput"] == {"text": "[WITHHELD: content not fully scanned]"}
    assert mcp["hookSpecificOutput"]["additionalContext"] == WITHHELD_NOTE
    assert "withheld" in mcp["systemMessage"] and "masked" not in mcp["systemMessage"]
    builtin = content_output({"content": {key: value for key, value in WITHHELD.items() if key != "updated_output"}},
                             "Bash")
    assert "updatedMCPToolOutput" not in builtin["hookSpecificOutput"]
    assert builtin["hookSpecificOutput"]["additionalContext"] == WITHHELD_NOTE
