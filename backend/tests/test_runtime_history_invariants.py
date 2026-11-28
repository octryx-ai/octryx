import uuid

from app.agent.runtime.message_helpers import _trim_messages_to_budget
from app.services.tool_artifact.summary import (
    build_tool_artifact_envelope,
    parse_tool_artifact_envelope,
    serialize_tool_artifact_envelope,
)
from app.services.tool_artifact.working_set import build_within_turn_working_set_messages


def _build_tool_message(tool_call_id: str, *, artifact_id: str | None = None, summary: str | None = None) -> dict:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": serialize_tool_artifact_envelope(
            build_tool_artifact_envelope(
                artifact_id=artifact_id or f"artifact-{tool_call_id}",
                tool_name="todo_read",
                payload={
                    "status": "ok",
                    "summary": summary or f"result-{tool_call_id}",
                    "items": [{"id": index, "value": "x" * 120} for index in range(6)],
                },
                include_result=True,
            )
        ),
    }


def _assistant_tool_call_ids(messages: list[dict]) -> set[str]:
    return {
        str(tool_call.get("id") or "").strip()
        for message in messages
        if message.get("role") == "assistant"
        for tool_call in list(message.get("tool_calls") or [])
        if str(tool_call.get("id") or "").strip()
    }


def _tool_result_ids(messages: list[dict]) -> set[str]:
    return {
        str(message.get("tool_call_id") or "").strip()
        for message in messages
        if message.get("role") == "tool" and str(message.get("tool_call_id") or "").strip()
    }


def _assert_no_dangling_tool_pairs(messages: list[dict]) -> None:
    assistant_ids = _assistant_tool_call_ids(messages)
    tool_ids = _tool_result_ids(messages)
    assert assistant_ids == tool_ids


def test_trim_messages_to_budget_preserves_surviving_multi_tool_chunk_under_pressure():
    messages = [
        {"role": "system", "content": "system " * 800},
        {"role": "user", "content": "old request " * 200},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-old-a", "function": {"name": "todo_read", "arguments": "{}"}},
                {"id": "call-old-b", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        _build_tool_message("call-old-a"),
        _build_tool_message("call-old-b"),
        {"role": "assistant", "content": "older narrative context " * 120},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-keep-a", "function": {"name": "todo_read", "arguments": "{}"}},
                {"id": "call-keep-b", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        _build_tool_message("call-keep-a"),
        _build_tool_message("call-keep-b"),
        {"role": "user", "content": "current request"},
    ]

    trimmed = _trim_messages_to_budget(messages, 900)

    assert trimmed[0]["role"] == "system"
    assert trimmed[-1] == {"role": "user", "content": "current request"}
    assert _assistant_tool_call_ids(trimmed) == {"call-keep-a", "call-keep-b"}
    assert _tool_result_ids(trimmed) == {"call-keep-a", "call-keep-b"}
    assert not any(message.get("tool_call_id") == "call-old-a" for message in trimmed)
    assert not any(message.get("tool_call_id") == "call-old-b" for message in trimmed)
    _assert_no_dangling_tool_pairs(trimmed)


def test_trim_messages_to_budget_keeps_current_tool_pairs_when_text_is_truncated():
    messages = [
        {"role": "system", "content": "system " * 4000},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-current-a", "function": {"name": "todo_read", "arguments": "{}"}},
                {"id": "call-current-b", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        _build_tool_message("call-current-a"),
        _build_tool_message("call-current-b"),
        {"role": "user", "content": "current request " * 1500},
    ]

    trimmed = _trim_messages_to_budget(messages, 300)

    assert trimmed[0]["role"] == "system"
    assert trimmed[-1]["role"] == "user"
    assert trimmed[0]["content"].endswith("...")
    assert trimmed[-1]["content"].endswith("...")
    assert _assistant_tool_call_ids(trimmed) == {"call-current-a", "call-current-b"}
    assert _tool_result_ids(trimmed) == {"call-current-a", "call-current-b"}
    _assert_no_dangling_tool_pairs(trimmed)


def test_trim_messages_to_budget_never_drops_the_only_user_message():
    # Live regression (coding pipeline run 7): the task prompt is a mid-history
    # user message followed by agent turns. Pre-dispatch compaction dropped it,
    # producing a userless conversation that both Bedrock ("conversation must
    # start with a user message") and Copilot rejected.
    messages = [
        {"role": "system", "content": "main system prompt"},
        {"role": "system", "content": "agent definition " * 200},
        {"role": "system", "content": "execution contract " * 200},
        {"role": "user", "content": "You are the governed coding agent. Execute the approved change."},
        {"role": "assistant", "content": "scope inspection " * 300},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-edit", "function": {"name": "todo_read", "arguments": "{}"}}],
        },
        _build_tool_message("call-edit"),
        {"role": "assistant", "content": "narration " * 300},
        {"role": "system", "content": "step reminder"},
    ]

    trimmed = _trim_messages_to_budget(messages, 400)

    user_messages = [m for m in trimmed if m.get("role") == "user"]
    assert user_messages, "the only user message must survive trimming"
    assert "governed coding agent" in user_messages[0]["content"]
    # The leading system block (governance contracts) survives as well.
    assert [m["role"] for m in trimmed[:3]] == ["system", "system", "system"]
    _assert_no_dangling_tool_pairs(trimmed)


def test_working_set_collapse_updates_multi_call_assistant_without_dangling_ids():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Inspect runtime history"},
        {
            "role": "assistant",
            "content": "I will gather two related artifacts.",
            "tool_calls": [
                {"id": "call-a", "function": {"name": "todo_read", "arguments": "{}"}},
                {"id": "call-b", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        _build_tool_message("call-a", summary="older result"),
        _build_tool_message("call-b", summary="newer result"),
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-c", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        _build_tool_message("call-c", summary="latest result"),
    ]

    pruned, stats = build_within_turn_working_set_messages(
        messages,
        token_budget=120,
        thinking_level="light",
        approx_chars_per_token=4,
    )

    first_assistant = next(
        message
        for message in pruned
        if message.get("role") == "assistant" and "gather two related artifacts" in str(message.get("content") or "")
    )
    remaining_ids = {
        str(tool_call.get("id") or "").strip() for tool_call in list(first_assistant.get("tool_calls") or [])
    }

    assert stats["collapsed_tool_messages"] >= 1
    assert remaining_ids == {"call-b"}
    assert "call-a" not in _tool_result_ids(pruned)
    _assert_no_dangling_tool_pairs(pruned)


def test_working_set_pressure_keeps_tool_envelopes_parseable_and_pairs_consistent():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Investigate runtime pressure"},
    ]
    for index in range(6):
        messages.append(
            {
                "role": "assistant",
                "content": f"tool batch {index}",
                "tool_calls": [
                    {
                        "id": f"call-{index}",
                        "function": {"name": "todo_read", "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append(
            _build_tool_message(
                f"call-{index}",
                artifact_id=str(uuid.uuid4()),
                summary=f"runtime result {index}",
            )
        )

    pruned, stats = build_within_turn_working_set_messages(
        messages,
        token_budget=220,
        thinking_level="light",
        approx_chars_per_token=4,
    )

    tool_messages = [message for message in pruned if message.get("role") == "tool"]
    assert stats["collapsed_tool_messages"] >= 1
    assert stats["snapshot_tool_messages"] >= 1
    assert all(parse_tool_artifact_envelope(message.get("content")) is not None for message in tool_messages)
    _assert_no_dangling_tool_pairs(pruned)
