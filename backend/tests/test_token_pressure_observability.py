from app.agent.engine.pre_dispatch._token_pressure_observability import build_token_pressure_observability_payload


def test_build_token_pressure_observability_payload_explains_before_and_after_totals():
    before_messages = [
        {"role": "system", "content": "runtime guardrails and policies"},
        {"role": "user", "content": "Older question"},
        {"role": "assistant", "content": "Investigating prior step"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": {"items": ["x" * 120, "y" * 120]}},
        {"role": "user", "content": "Current request with important constraints"},
    ]
    after_messages = [
        {"role": "system", "content": "runtime guardrails and policies"},
        {"role": "assistant", "content": "Compacted earlier history into a short summary."},
        {"role": "tool", "tool_call_id": "call-1", "content": {"summary": "Older tool result snapshot"}},
        {"role": "user", "content": "Current request with important constraints"},
    ]

    payload = build_token_pressure_observability_payload(
        before_messages,
        after_messages,
        approx_chars_per_token=4,
        compaction_stats={"collapsed_tool_messages": 1, "collapsed_assistant_tool_messages": 1},
    )

    assert payload["kind"] == "token_pressure_breakdown"
    assert payload["estimation"] == {
        "approx_chars_per_token": 4,
        "estimated_only": True,
        "not_for_billing": True,
    }
    assert (
        payload["before_compaction"]["estimated_total_tokens"] > payload["after_compaction"]["estimated_total_tokens"]
    )
    assert payload["compaction"]["estimated_tokens_before"] == payload["before_compaction"]["estimated_total_tokens"]
    assert payload["compaction"]["estimated_tokens_after"] == payload["after_compaction"]["estimated_total_tokens"]
    assert payload["compaction"]["estimated_tokens_reduced"] > 0
    assert payload["compaction"]["collapsed_tool_messages"] == 1
    assert payload["compaction"]["collapsed_assistant_tool_messages"] == 1


def test_build_token_pressure_observability_payload_separates_system_history_tool_and_current_user():
    before_messages = [
        {"role": "system", "content": "System policy"},
        {"role": "user", "content": "Earlier request"},
        {"role": "assistant", "content": "Earlier answer"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-2", "function": {"name": "search_docs", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-2", "content": "tool result payload"},
        {"role": "user", "content": "Newest user request"},
    ]

    payload = build_token_pressure_observability_payload(before_messages, before_messages, approx_chars_per_token=4)
    contributions = payload["before_compaction"]["contributions"]

    assert contributions["system"]["message_count"] == 1
    assert contributions["history"]["message_count"] == 2
    assert contributions["tool"]["message_count"] == 2
    assert contributions["current_user"]["message_count"] == 1
    assert contributions["tool"]["estimated_tokens"] > 0
    assert contributions["current_user"]["estimated_tokens"] > 0


def test_build_token_pressure_observability_payload_uses_after_messages_when_before_has_no_user_message():
    before_messages = [
        {"role": "system", "content": "System policy"},
        {"role": "assistant", "content": "Summarized carry-over context"},
    ]
    after_messages = [
        {"role": "system", "content": "System policy"},
        {"role": "assistant", "content": "Summarized carry-over context"},
        {"role": "user", "content": "Fresh user request"},
    ]

    payload = build_token_pressure_observability_payload(before_messages, after_messages, approx_chars_per_token=4)

    assert payload["before_compaction"]["contributions"]["current_user"]["message_count"] == 0
    assert payload["after_compaction"]["contributions"]["current_user"]["message_count"] == 1
    assert payload["compaction"]["message_count_before"] == 2
    assert payload["compaction"]["message_count_after"] == 3
    assert payload["compaction"]["messages_removed"] == 0
