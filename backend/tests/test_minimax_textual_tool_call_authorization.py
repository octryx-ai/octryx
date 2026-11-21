"""Text-derived tool calls are audited against the turn's authorization and tool definitions, quoted material is never a call, and a truncated opener gets a retry nudge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from app.agent.core.guards.response_guards import (  # noqa: E402
    is_non_substantive_assistant_response,
    is_transitional_assistant_response,
)
from app.agent.loops.response._loop_response_guards import _workflow_catalog_prompted  # noqa: E402
from app.agent.loops.response._loop_response_transition_inputs import TransitionGuardInputs  # noqa: E402
from app.agent.loops.response._loop_response_transitions import (  # noqa: E402
    handle_transition_response_guards,
)
from app.agent.loops.runtime._loop_textual_tool_repair import (  # noqa: E402
    audit_text_derived_tool_calls,
)
from app.agent.providers.inline_tool_calls import parse_inline_tool_calls  # noqa: E402
from app.services.workflow_routing.model_catalog import (  # noqa: E402
    MODEL_WORKFLOW_CATALOG_PROMPT_MARKER,
)


def _snapshot_with_allowlist(*names: str) -> dict:
    return {"context_plan": {"tool_allowlist": list(names)}}


def _inline_call(name: str, arguments: dict | str) -> dict:
    return {
        "id": "inline_call_0",
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        },
    }


def _offered(*names: str) -> list[dict]:
    return [{"type": "function", "function": {"name": name}} for name in names]


async def _noop_persist(**kwargs):
    return None


class _DummyDB:
    async def commit(self):
        return None


# --- Poisoning protection ---------------------------------------------------
def test_json_object_line_inside_code_fence_is_quoted_material_not_a_call():
    content = (
        "So sähe der Aufruf aus:\n```\n"
        '{"name": "select_workflow", "input": {"workflow_key": "developer-diagram-routing"}}\n'
        "```"
    )
    cleaned, calls = parse_inline_tool_calls(content)
    assert calls == []
    assert cleaned == content


def test_audit_keeps_authorized_text_derived_call_and_stamps_counter():
    snapshot = _snapshot_with_allowlist("select_workflow")
    calls = [_inline_call("select_workflow", {"workflow_key": "developer-diagram-routing"})]
    audited = audit_text_derived_tool_calls(
        tool_calls=calls,
        context_snapshot=snapshot,
        current_allowed_tool_names=set(),
        capability_type="diagnosis",
        offered_tool_definitions=_offered("select_workflow"),
    )
    assert audited == calls
    audit = snapshot["repaired_textual_tool_calls"]
    assert audit["count"] == 1
    assert audit["tool_names"] == ["select_workflow"]
    assert audit["rejected"] == []


def test_audit_rejects_tool_name_outside_turn_authorization():
    # A tool that exists on the platform but was neither offered to the model
    # this turn nor allowed by any policy: quoted/poisoned text must not run it.
    snapshot = _snapshot_with_allowlist("select_workflow")
    audited = audit_text_derived_tool_calls(
        tool_calls=[_inline_call("aws_read_operation", {"service": "rds"})],
        context_snapshot=snapshot,
        current_allowed_tool_names=set(),
        capability_type="diagnosis",
        offered_tool_definitions=_offered("select_workflow"),
    )
    assert audited == []
    audit = snapshot["repaired_textual_tool_calls"]
    assert audit["count"] == 0
    assert audit["rejected"] == [{"tool_name": "aws_read_operation", "reason": "outside_turn_authorization"}]


def test_audit_rejects_unknown_tool_name():
    snapshot = _snapshot_with_allowlist("select_workflow")
    audited = audit_text_derived_tool_calls(
        tool_calls=[_inline_call("delete_everything", {})],
        context_snapshot=snapshot,
        current_allowed_tool_names=set(),
        capability_type="diagnosis",
        offered_tool_definitions=_offered("select_workflow"),
    )
    assert audited == []
    assert snapshot["repaired_textual_tool_calls"]["rejected"] == [
        {"tool_name": "delete_everything", "reason": "unknown_tool"}
    ]


def test_audit_rejects_non_object_arguments():
    snapshot = _snapshot_with_allowlist("select_workflow")
    audited = audit_text_derived_tool_calls(
        tool_calls=[_inline_call("select_workflow", '["not", "an", "object"]')],
        context_snapshot=snapshot,
        current_allowed_tool_names=set(),
        capability_type="diagnosis",
        offered_tool_definitions=_offered("select_workflow"),
    )
    assert audited == []
    assert snapshot["repaired_textual_tool_calls"]["rejected"] == [
        {"tool_name": "select_workflow", "reason": "arguments_not_object"}
    ]


def test_audit_leaves_native_tool_calls_untouched():
    snapshot: dict = {}
    native_call = {
        "id": "call_abc123",
        "type": "function",
        "function": {"name": "select_workflow", "arguments": "{}"},
    }
    audited = audit_text_derived_tool_calls(
        tool_calls=[native_call],
        context_snapshot=snapshot,
        current_allowed_tool_names=set(),
        capability_type="diagnosis",
        offered_tool_definitions=_offered("select_workflow"),
    )
    assert audited is None
    assert "repaired_textual_tool_calls" not in snapshot


def test_workflow_catalog_prompt_marks_tools_available():
    prompted = {"system_prompt": f"Base rules.\n{MODEL_WORKFLOW_CATALOG_PROMPT_MARKER}\n- developer-diagram-routing"}
    assert _workflow_catalog_prompted(prompted)
    assert not _workflow_catalog_prompted({"system_prompt": "Base rules without a catalog."})
    assert not _workflow_catalog_prompted({})
    assert not _workflow_catalog_prompted(None)


@pytest.mark.asyncio
async def test_truncated_tool_call_opener_gets_retry_nudge_without_native_definitions():
    # Regression: final turn with content exactly `<tool_call>` on a turn with
    # ZERO native tool definitions (catalog-prompted runtime). The turn must be
    # nudged to retry, not accepted as a final answer.
    messages: list[dict[str, str]] = []
    outcome = await handle_transition_response_guards(TransitionGuardInputs(
        db=_DummyDB(),
        session_id="session-minimax",
        runtime={"provider_name": "minimax"},
        response={"usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        request_messages=[
            {"role": "user", "content": "Erstelle mir ein OAuth Authorization Code Flow Diagramm mit PKCE."}
        ],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 2},
        usage_model="MiniMax-M3",
        content="<tool_call>",
        tool_calls=None,
        current_tool_definitions=[],
        current_step=None,
        has_followup_steps=False,
        turn_tool_history=[],
        consecutive_non_progress_response_count=0,
        consecutive_transitional_response_count=0,
        is_transitional_assistant_response=is_transitional_assistant_response,
        is_non_substantive_assistant_response=is_non_substantive_assistant_response,
        looks_like_step_completion_summary=lambda text: False,
        build_stalled_step_message=lambda step: "stalled",
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_persist,
        persist_traced_assistant_message=_noop_persist,
        workflow_id="",
        request_analysis={},
    ))
    assert outcome["action"] == "continue"
    assert any(message.get("role") == "system" for message in messages)


def test_audit_offered_definitions_authorize_without_policy_allowlist():
    # No policy/contract/catalog allowlist at all: the tools OFFERED to the
    # model this turn are the authorization source (Claude-Code semantics).
    snapshot: dict = {}
    calls = [_inline_call("select_workflow", {"workflow_key": "developer-diagram-routing"})]
    audited = audit_text_derived_tool_calls(
        tool_calls=calls,
        context_snapshot=snapshot,
        current_allowed_tool_names=set(),
        capability_type="diagnosis",
        offered_tool_definitions=_offered("select_workflow", "create_diagram"),
    )
    assert audited == calls
    assert snapshot["repaired_textual_tool_calls"]["count"] == 1
