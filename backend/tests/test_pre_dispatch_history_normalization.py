from app.agent.engine.pre_dispatch._history_invariant_normalization import (
    normalize_pre_dispatch_history,
    plan_pre_dispatch_history_normalization,
)


def test_plan_pre_dispatch_history_normalization_accepts_canonical_history():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Inspect runtime"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-a", "function": {"name": "todo_read", "arguments": "{}"}},
                {"id": "call-b", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-a", "content": '{"ok": true}'},
        {"role": "tool", "tool_call_id": "call-b", "content": '{"ok": true}'},
        {"role": "user", "content": "Continue"},
    ]

    plan = plan_pre_dispatch_history_normalization(messages)

    assert plan.requires_normalization is False
    assert plan.findings == ()
    assert plan.assistant_rewrites == ()
    assert plan.drop_message_indexes == ()
    assert plan.canonical_tool_call_ids == ("call-a", "call-b")
    assert plan.valid_tool_result_ids == ("call-a", "call-b")


def test_normalize_pre_dispatch_history_drops_orphans_and_dangling_tool_calls():
    messages = [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": "I will inspect and then report.",
            "tool_calls": [
                {"id": "call-keep", "function": {"name": "todo_read", "arguments": "{}"}},
                {"id": "call-drop", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-keep", "content": '{"ok": true}'},
        {"role": "tool", "tool_call_id": "call-orphan", "content": '{"ok": true}'},
    ]

    normalized, plan = normalize_pre_dispatch_history(messages)

    assert plan.requires_normalization is True
    assert plan.canonical_tool_call_ids == ("call-keep",)
    assert plan.dangling_assistant_tool_call_ids == ("call-drop",)
    assert plan.orphan_tool_result_ids == ("call-orphan",)
    assert plan.drop_message_indexes == (3,)
    assert {finding.code for finding in plan.findings} == {
        "dangling_assistant_tool_call",
        "orphan_tool_result",
    }
    assert normalized == [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": "I will inspect and then report.",
            "tool_calls": [
                {"id": "call-keep", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-keep", "content": '{"ok": true}'},
    ]


def test_normalize_pre_dispatch_history_converts_empty_tool_call_message_to_content_only():
    messages = [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": "I will inspect the workspace first.",
            "tool_calls": [
                {"id": "call-missing", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        {"role": "user", "content": "Continue"},
    ]

    normalized, plan = normalize_pre_dispatch_history(messages)

    assert plan.requires_normalization is True
    assert plan.dangling_assistant_tool_call_ids == ("call-missing",)
    assert len(plan.assistant_rewrites) == 1
    assert plan.assistant_rewrites[0].drop_tool_calls_field is True
    assert normalized == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Continue"},
    ]


def test_normalize_pre_dispatch_history_drops_tool_only_assistant_without_results():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Find Report Builder details"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-missing", "function": {"name": "knowledge_search", "arguments": "{}"}},
            ],
        },
        {"role": "user", "content": "Please provide the structured summary"},
    ]

    normalized, plan = normalize_pre_dispatch_history(messages)

    assert plan.requires_normalization is True
    assert plan.dangling_assistant_tool_call_ids == ("call-missing",)
    assert plan.drop_message_indexes == (2,)
    assert {finding.code for finding in plan.findings} == {
        "dangling_assistant_tool_call",
        "empty_assistant_message",
    }
    assert normalized == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Find Report Builder details"},
        {"role": "user", "content": "Please provide the structured summary"},
    ]


def test_normalize_pre_dispatch_history_deduplicates_ids_and_missing_identifiers():
    messages = [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "todo_read", "arguments": "{}"}},
                {"id": "call-1", "function": {"name": "todo_read", "arguments": "{}"}},
                {"function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": '{"ok": true}'},
        {"role": "tool", "tool_call_id": "call-1", "content": '{"ok": true, "duplicate": true}'},
        {"role": "tool", "content": '{"ok": false}'},
    ]

    normalized, plan = normalize_pre_dispatch_history(messages)

    assert plan.requires_normalization is True
    assert plan.canonical_tool_call_ids == ("call-1",)
    assert plan.valid_tool_result_ids == ("call-1",)
    assert plan.drop_message_indexes == (3, 4)
    assert {finding.code for finding in plan.findings} == {
        "assistant_tool_call_missing_id",
        "duplicate_assistant_tool_call_id",
        "duplicate_tool_result",
        "tool_result_missing_id",
    }
    assert normalized == [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": '{"ok": true}'},
    ]


def test_normalize_pre_dispatch_history_drops_leading_assistant_before_user():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "Diagram complete.\n\nArtifact: `diagram://abc`."},
        {"role": "user", "content": "Change the structure of diagram://abc"},
    ]

    normalized, plan = normalize_pre_dispatch_history(messages)

    assert plan.requires_normalization is True
    assert plan.drop_message_indexes == (1,)
    assert {finding.code for finding in plan.findings} == {"leading_non_user_message"}
    assert normalized == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Change the structure of diagram://abc"},
    ]
