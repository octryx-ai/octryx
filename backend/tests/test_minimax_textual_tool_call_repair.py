"""MiniMax-M3 textual tool-call repair — fixture tests with the real captured
payloads of the 8 documented E2E failures (raw assistant outputs pulled from
turn_traces).

A turn must never die on a tool call the model emitted as text: the catalogued
variants are parsed, validated against the tool definitions and the turn's
authorization set, and executed through the normal dispatch. Quoted/fenced
tool-call text and tool names outside the turn's authorization are NEVER
executed (poisoning protection).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from app.agent.core.guards.response_guards import (  # noqa: E402
    is_non_substantive_assistant_response,
    is_transitional_assistant_response,
)
from app.agent.providers.inline_tool_calls import parse_inline_tool_calls  # noqa: E402

# --- V1: JSON-object line with the Anthropic-style "input" key ------------
# Synthetic regression sample for an unrecovered final message (the turn
# ended with this text because the "input" key was not recovered).
V1_PAYLOAD = (
    "Ich erstelle das Diagramm über den vorgesehenen Workflow als draw.io-Artefakt.\n"
    '{"name": "select_workflow", "input": {"workflow_key": "developer-diagram-routing"}}'
)


# --- V7: unterminated <tool_call> with Tool:/Args: dash-list grammar --------
# Regression sample for unterminated textual tool-call blocks: stream
# marker + opener without closing tag, YAML-ish body, one or many Tool groups.
V7_SINGLE = (
    "Ich erstelle dir das OAuth Authorization Code Flow mit PKCE als draw.io-Diagramm über den "
    "vorgesehenen Workflow.]<]minimax[>[<tool_call>\n"
    "Tool: select_workflow\n"
    "Args:\n"
    "- workflow_key: developer-diagram-routing"
)


V7_MULTI = (
    "Ich rufe den relevanten Kontext für Developer-Diagramme ab und rendere das Diagramm dann über "
    "den deterministischen Builder.]<]minimax[>[<tool_call>\n"
    "Tool: instruction_get\n"
    "Args:\n"
    "- key: developer-diagram-routing\n"
    "Tool: create_diagram\n"
    "Args:\n"
    "- diagram_type: sequence\n"
    "- title: OAuth 2.0 Authorization Code Flow with PKCE\n"
    '- participants: ["User (Browser)", "Client App (SPA/Mobile)", "Authorization Server", "Resource Server"]\n'
    "- description: Sequenzdiagramm für OAuth 2.0 Authorization Code Flow mit PKCE (RFC 7636)."
)


def test_v1_json_object_line_with_input_key_is_recovered():
    cleaned, calls = parse_inline_tool_calls(V1_PAYLOAD)
    assert [c["function"]["name"] for c in calls] == ["select_workflow"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"workflow_key": "developer-diagram-routing"}
    assert "select_workflow" not in cleaned
    assert cleaned.startswith("Ich erstelle das Diagramm")


def test_v1_json_object_line_with_nested_arguments_is_recovered():
    content = '{"name": "select_workflow", "input": {"workflow_key": "developer-diagram-routing", "hints": {"kind": "auth_flow"}}}'
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls and json.loads(calls[0]["function"]["arguments"]) == {
        "workflow_key": "developer-diagram-routing",
        "hints": {"kind": "auth_flow"},
    }


# --- V2: whole-block JSON inside <tool_call> with "input" ------------------
# Regression: the block parsed and the name survived,
# but the arguments were SILENTLY dropped to {} — producing a
# `workflow_key is required` retry loop (4x) until the turn died.
def test_v2_tool_call_block_json_with_input_key_preserves_arguments():
    content = (
        "Ich starte den passenden Workflow.\n<tool_call>\n"
        '{"name": "select_workflow", "input": {"workflow_key": "developer-diagram-routing"}}\n'
        "</tool_call>"
    )
    cleaned, calls = parse_inline_tool_calls(content)
    assert calls and calls[0]["function"]["name"] == "select_workflow"
    assert json.loads(calls[0]["function"]["arguments"]) == {"workflow_key": "developer-diagram-routing"}
    assert "<tool_call>" not in cleaned


def test_v2_tool_call_block_json_with_parameters_key_preserves_arguments():
    content = '<tool_call>{"name": "create_diagram", "parameters": {"title": "OAuth PKCE"}}</tool_call>'
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls and json.loads(calls[0]["function"]["arguments"]) == {"title": "OAuth PKCE"}


def test_v2_fenced_json_array_with_input_key_is_recovered():
    content = '```json\n[{"name": "select_workflow", "input": {"workflow_key": "developer-diagram-routing"}}]\n```'
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls and json.loads(calls[0]["function"]["arguments"]) == {"workflow_key": "developer-diagram-routing"}


# --- V3: truncated <tool_call> opener --------------------------------------
# Regression sample for a truncated tool-call opener on a final turn: generation
# stopped mid-emission. Nothing is recoverable; the content must survive
# untouched so the non-substantive guard sees it and nudges a retry.
def test_v3_lone_truncated_tool_call_opener_is_not_a_call_and_survives():
    cleaned, calls = parse_inline_tool_calls("<tool_call>")
    assert calls == []
    assert cleaned == "<tool_call>"
    assert is_non_substantive_assistant_response(cleaned, None)


# --- V4: stray </tool_call> residue ----------------------------------------
# Regression: a bare `</tool_call>` persisted next to a recovered call.
def test_v4_stray_closer_residue_is_stripped_when_a_call_was_recovered():
    content = (
        "<tool_call>\n"
        '{"name": "select_workflow", "input": {"workflow_key": "developer-diagram-routing"}}\n'
        "</tool_call>\n</tool_call>"
    )
    cleaned, calls = parse_inline_tool_calls(content)
    assert calls and calls[0]["function"]["name"] == "select_workflow"
    assert "</tool_call>" not in cleaned and "<tool_call>" not in cleaned


# --- V5: announcement-only prose (no call in any channel) ------------------
# Regression samples for announcement-only prose that must not be accepted as a final answer.
def test_v5_workflow_selection_announcements_are_transitional():
    assert is_transitional_assistant_response(
        "I am starting with the selection of the matching workflow for a developer/auth flow diagram.",
        None,
        True,
    )
    assert is_transitional_assistant_response(
        "I'll start the matching workflow with the correct key `developer-diagram-routing`.",
        None,
        True,
    )
    assert is_transitional_assistant_response(
        "I'm selecting the workflow key now.",
        None,
        True,
    )


def test_v5_substantive_final_answer_is_not_transitional():
    assert not is_transitional_assistant_response(
        "The diagram was created. Artifact: `diagram://5515f510`. It shows the OAuth "
        "Authorization Code Flow with PKCE as a sequence diagram.",
        None,
        True,
    )


def test_v7_unterminated_tool_call_with_tool_args_grammar_is_recovered():
    cleaned, calls = parse_inline_tool_calls(V7_SINGLE)
    assert [c["function"]["name"] for c in calls] == ["select_workflow"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"workflow_key": "developer-diagram-routing"}
    assert "<tool_call>" not in cleaned
    assert cleaned.startswith("Ich erstelle dir das OAuth")


def test_v7_multiple_tool_groups_with_json_values_are_recovered():
    _cleaned, calls = parse_inline_tool_calls(V7_MULTI)
    assert [c["function"]["name"] for c in calls] == ["instruction_get", "create_diagram"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"key": "developer-diagram-routing"}
    create_args = json.loads(calls[1]["function"]["arguments"])
    assert create_args["diagram_type"] == "sequence"
    assert create_args["participants"] == [
        "User (Browser)",
        "Client App (SPA/Mobile)",
        "Authorization Server",
        "Resource Server",
    ]


def test_v7_terminated_tool_call_with_tool_args_grammar_is_recovered():
    content = "<tool_call>\nTool: select_workflow\nArgs:\n- workflow_key: developer-diagram-routing\n</tool_call>"
    cleaned, calls = parse_inline_tool_calls(content)
    assert calls and calls[0]["function"]["name"] == "select_workflow"
    assert json.loads(calls[0]["function"]["arguments"]) == {"workflow_key": "developer-diagram-routing"}
    assert "<tool_call>" not in cleaned


def test_v7_unterminated_opener_with_unparseable_prose_body_is_not_a_call():
    content = "<tool_call>\nSo etwas wie ein Werkzeugaufruf, aber nur Prosa ohne Grammatik."
    cleaned, calls = parse_inline_tool_calls(content)
    assert calls == []
    assert cleaned == content
