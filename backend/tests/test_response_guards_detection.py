"""Detecting transitional, textual tool request and coding intent responses, governed coding evidence and no-tool signatures."""

from __future__ import annotations

import json

from app.agent.core.guards.response_guards import (
    assistant_no_tool_response_signature,
    assistant_no_tool_response_similarity,
    is_non_substantive_assistant_response,
    is_transitional_assistant_response,
    is_transitional_tool_call_preamble,
    looks_like_step_completion_summary,
    strip_textual_tool_request_preamble,
)
from app.agent.loops.outcome._loop_post_tool_coding_delivery import (
    _governed_coding_evidence_budget_exceeded,
)
from app.agent.loops.response._loop_messages import (
    _looks_like_coding_intent_only_response,
)
from app.agent.loops.response._loop_response_coding import (
    _has_governed_coding_delivery,
    _looks_like_explicit_coding_blocker_or_noop,
)
from app.agent.loops.response._loop_response_guards import _visible_tool_names
from app.agent.loops.runtime._loop_textual_tool_repair import repair_textual_tool_request


def test_transitional_assistant_response_detects_follow_up_language() -> None:
    assert is_transitional_assistant_response(
        "Now let me check existing Confluence documentation to determine if updates are needed.",
        None,
        True,
    )
    assert is_transitional_assistant_response(
        "Let me try again with a higher timeout:",
        None,
        True,
    )
    assert not is_transitional_assistant_response(
        "The requested release was created successfully. Let me know if you need anything else.",
        None,
        True,
    )


def test_transitional_tool_call_preamble_detects_action_intent() -> None:
    assert is_transitional_tool_call_preamble(
        "I will check the latest changes for report-builder. First I fetch the relevant commits from Bitbucket.",
        [{"id": "call-2", "function": {"name": "list_recent_bitbucket_commits", "arguments": "{}"}}],
    )


def test_textual_tool_request_is_non_substantive_without_structured_tool_call() -> None:
    assert is_non_substantive_assistant_response("Tool request knowledge_get: {'key': 'Report Builder'}", None)


def test_textual_tool_request_preamble_is_stripped_when_answer_text_remains() -> None:
    content = (
        "Tool request instruction_get: {'domain': 'knowledge'}\n\n"
        "I need the project ID to look up Report Builder knowledge."
    )

    assert strip_textual_tool_request_preamble(content) == "I need the project ID to look up Report Builder knowledge."
    assert strip_textual_tool_request_preamble("Tool request knowledge_get: {'key': 'Report Builder'}").startswith(
        "Tool request knowledge_get"
    )


def test_visible_tool_names_omits_meta_tools_and_deduplicates() -> None:
    names = _visible_tool_names(
        [
            {"function": {"name": "read_workspace_file"}},
            {"function": {"name": "load_tool_artifact"}},
            {"function": {"name": "read_workspace_file"}},
            {"function": {"name": "run_test_suite"}},
        ]
    )

    assert names == ["read_workspace_file", "run_test_suite"]


def test_governed_coding_delivery_requires_change_or_pr_evidence() -> None:
    assert not _has_governed_coding_delivery(
        [
            {"tool_name": "prepare_bitbucket_repository", "result": {"ok": True}},
            {"tool_name": "bash", "result": {"exit_code": 0}},
            {"tool_name": "read_workspace_file", "result": {"content": "x"}},
        ]
    )
    assert _has_governed_coding_delivery(
        [
            {"tool_name": "edit_workspace_file", "result": {"relative_path": "terraform/base/main.tf"}},
            {"tool_name": "run_cli_command", "result": {"exit_code": 0}},
        ]
    )


def test_governed_coding_blocker_or_noop_is_explicit() -> None:
    assert _looks_like_explicit_coding_blocker_or_noop("Blocked: source changed after the approved plan.")
    assert _looks_like_explicit_coding_blocker_or_noop("No code changes are required after validation.")
    assert not _looks_like_explicit_coding_blocker_or_noop("I believe the correct approach is to remove one file.")


def test_governed_coding_evidence_budget_reminds_then_stops_read_only_loops() -> None:
    history = [
        {"tool_name": "prepare_bitbucket_repository", "result": {"ok": True}},
        *[
            {"tool_name": "read_workspace_file", "result": {"path": f"file-{index}.tf"}}
            for index in range(4)
        ],
        *[{"tool_name": "bash", "result": {"exit_code": 0, "command": f"grep {index}"}} for index in range(3)],
    ]

    reminder = _governed_coding_evidence_budget_exceeded(
        workflow_contract={"workflow_id": "coding_change_tdd", "verification_contract": {"commands": ["pytest"]}},
        history=history,
        limit=8,
    )

    assert reminder is not None
    assert reminder["evidence_tool_calls"] == 8
    assert reminder["hard_stop"] is False
    hard_stop = _governed_coding_evidence_budget_exceeded(
        workflow_contract={"workflow_id": "coding_change_tdd", "verification_contract": {"commands": ["pytest"]}},
        history=[
            *history,
            *[
                {"tool_name": "read_workspace_file", "result": {"path": f"later-{index}.tf"}}
                for index in range(8)
            ],
        ],
        limit=8,
    )
    assert hard_stop is not None
    assert hard_stop["hard_stop"] is True
    assert _governed_coding_evidence_budget_exceeded(
        workflow_contract={"workflow_id": "coding_change_tdd", "verification_contract": {"commands": ["pytest"]}},
        history=[*history, {"tool_name": "edit_workspace_file", "result": {"path": "terraform/base/main.tf"}}],
        limit=8,
    ) is None


def test_mixed_textual_tool_request_is_repaired_when_authorized() -> None:
    context_snapshot = {"session_tool_catalog": {"entries": [{"name": "knowledge_search"}]}}
    tool_calls = repair_textual_tool_request(
        content="I found a Jira ticket and will now search more. Tool request knowledge_search: {'query': 'Alice Example'}",
        tool_calls=None,
        context_snapshot=context_snapshot,
        current_allowed_tool_names=set(),
        capability_type="diagnosis",
    )

    assert tool_calls is not None
    assert tool_calls[0]["function"]["name"] == "knowledge_search"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {"query": "Alice Example"}


def test_coding_intent_only_response_detects_shared_english_and_german_phrases() -> None:
    assert _looks_like_coding_intent_only_response("Now I will implement the fix and run the verification afterwards.")
    assert _looks_like_coding_intent_only_response("Next I will run the tests and summarize the result.")
    assert not _looks_like_coding_intent_only_response("```python\nprint('already executing')\n```")


def test_no_tool_signature_and_similarity_stay_stable() -> None:
    first = assistant_no_tool_response_signature(
        "## Step 3 Complete: Knowledge Map Successfully Updated\n\nI have updated 5 entries from `repo-a`."
    )
    second = assistant_no_tool_response_signature(
        "## Step 3 Complete: Knowledge Map Successfully Updated\n\nI have updated 7 entries from `repo-b`."
    )

    assert first is not None
    assert first == second
    assert looks_like_step_completion_summary("## Step 1 Complete: Repository Inventory Classification")
    assert (
        assistant_no_tool_response_similarity(
            "## Step 1 Complete: Repository Inventory Classification",
            "## Step 1 Complete: Repository-Inventar lesen ✅",
        )
        >= 0.72
    )
