from app.agent.engine.pre_dispatch._pre_dispatch_runtime_guard import prepare_pre_dispatch_runtime_messages


def test_prepare_pre_dispatch_runtime_messages_normalizes_and_records_token_pressure():
    messages = [
        {"role": "system", "content": "system " * 1200},
        {
            "role": "assistant",
            "content": "I started an earlier tool call.",
            "tool_calls": [
                {"id": "call-keep", "function": {"name": "todo_read", "arguments": "{}"}},
                {"id": "call-drop", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-keep", "content": '{"ok": true}'},
        {"role": "tool", "tool_call_id": "call-orphan", "content": '{"ok": false}'},
        {"role": "user", "content": "current request " * 400},
    ]

    result = prepare_pre_dispatch_runtime_messages(
        messages=messages,
        runtimes=[{"provider_name": "copilot", "model": "claude-haiku-4.5"}],
        max_tokens=1024,
        reasoning_effort="high",
        approx_chars_per_token=4,
    )

    assert result.normalization_plan.requires_normalization is True
    assert result.token_pressure_payload["kind"] == "token_pressure_breakdown"
    assert result.token_pressure_payload["history_invariant"]["requires_normalization"] is True
    assert result.token_pressure_payload["history_invariant"]["drop_message_count"] >= 1
    assert result.messages[-1]["role"] == "user"
    assert not any(message.get("tool_call_id") == "call-orphan" for message in result.messages)

    assistant_rewrite = next(
        rewrite
        for rewrite in result.normalization_plan.assistant_rewrites
        if "call-keep" in rewrite.kept_tool_call_ids
    )
    assert assistant_rewrite.dropped_tool_call_ids == ("call-drop",)
    assert "call-keep" in result.normalization_plan.canonical_tool_call_ids
    assert result.token_pressure_payload["compaction"]["pre_dispatch_guard"] is True
