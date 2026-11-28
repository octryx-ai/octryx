"""Building within-turn working set messages: snapshots of older tool results and removal of dangling tool calls."""

from app.services.tool_artifact import (
    build_tool_artifact_envelope,
    build_turn_working_summary_message,
    build_within_turn_working_set_messages,
    parse_tool_artifact_envelope,
    serialize_tool_artifact_envelope,
)


def test_build_within_turn_working_set_messages_snapshots_older_tool_results():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Investigate deployment failure"},
    ]
    for index in range(5):
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call-{index}",
                        "function": {"name": "todo_read", "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": f"call-{index}",
                "content": serialize_tool_artifact_envelope(
                    build_tool_artifact_envelope(
                        artifact_id=f"artifact-{index}",
                        tool_name="todo_read",
                        payload={
                            "status": "ok",
                            "summary": f"result-{index}",
                            "items": [{"id": item, "value": "x" * 50} for item in range(4)],
                        },
                        include_result=True,
                    )
                ),
            }
        )

    pruned, stats = build_within_turn_working_set_messages(
        messages,
        token_budget=600,
        thinking_level="light",
        approx_chars_per_token=4,
    )

    tool_envelopes = [
        parse_tool_artifact_envelope(message["content"]) for message in pruned if message.get("role") == "tool"
    ]
    assert all(envelope is not None for envelope in tool_envelopes)
    assert len(tool_envelopes) <= 2
    assert sum(1 for envelope in tool_envelopes if "result" in (envelope or {})) <= 2
    assert stats["tool_messages_total"] == 5
    assert stats["collapsed_tool_messages"] >= 3

    summary_message = build_turn_working_summary_message(pruned, thinking_level="light")
    collapsed_summary = next(
        (
            message
            for message in pruned
            if message.get("role") == "system" and "Earlier Tool Progress Summary" in str(message.get("content") or "")
        ),
        None,
    )
    assert collapsed_summary is not None
    assert "artifact-2" in str(collapsed_summary["content"])
    assert summary_message is None
    dangling_tool_call_ids = {
        str(tool_call.get("id") or "").strip()
        for message in pruned
        if message.get("role") == "assistant"
        for tool_call in list(message.get("tool_calls") or [])
    }
    resolved_tool_call_ids = {
        str(message.get("tool_call_id") or "").strip() for message in pruned if message.get("role") == "tool"
    }
    assert dangling_tool_call_ids <= resolved_tool_call_ids


def test_build_within_turn_working_set_messages_removes_dangling_tool_calls_but_keeps_content():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Implement divide"},
        {
            "role": "assistant",
            "content": "I will create calculator.py first.",
            "tool_calls": [
                {
                    "id": "call-create-file",
                    "function": {"name": "write_workspace_file", "arguments": '{"path":"calculator.py"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-create-file",
            "content": serialize_tool_artifact_envelope(
                build_tool_artifact_envelope(
                    artifact_id="artifact-create-file",
                    tool_name="write_workspace_file",
                    payload={"status": "ok", "path": "calculator.py"},
                    include_result=True,
                )
            ),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-run-tests",
                    "function": {"name": "run_test_suite", "arguments": '{"framework":"pytest"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-run-tests",
            "content": serialize_tool_artifact_envelope(
                build_tool_artifact_envelope(
                    artifact_id="artifact-run-tests",
                    tool_name="run_test_suite",
                    payload={"status": "ok", "passed": 4},
                    include_result=True,
                )
            ),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-review",
                    "function": {"name": "self_review_workspace_diff", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-review",
            "content": serialize_tool_artifact_envelope(
                build_tool_artifact_envelope(
                    artifact_id="artifact-review",
                    tool_name="self_review_workspace_diff",
                    payload={"status": "ok", "issues": []},
                    include_result=True,
                )
            ),
        },
    ]

    pruned, _stats = build_within_turn_working_set_messages(
        messages,
        token_budget=120,
        thinking_level="light",
        approx_chars_per_token=4,
    )

    assistant_messages = [message for message in pruned if message.get("role") == "assistant"]
    preserved_content_message = next(
        message for message in assistant_messages if "create calculator.py first" in str(message.get("content") or "")
    )
    assert "tool_calls" not in preserved_content_message
    remaining_tool_call_ids = {
        str(tool_call.get("id") or "").strip()
        for message in assistant_messages
        for tool_call in list(message.get("tool_calls") or [])
    }
    resolved_tool_call_ids = {
        str(message.get("tool_call_id") or "").strip() for message in pruned if message.get("role") == "tool"
    }
    assert remaining_tool_call_ids <= resolved_tool_call_ids
