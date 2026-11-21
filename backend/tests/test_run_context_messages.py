from app.agent.core.context.run_context_messages import (
    build_prompt_messages,
    prepend_structured_thread_context,
    split_current_turn_from_history,
)
from app.agent.core.prompts.prompt_parts import (
    SystemPromptParts,
    authored_section,
    platform_section,
    untrusted_section,
)
from app.models import Message


def test_split_current_turn_from_history_excludes_inflight_user_message() -> None:
    assistant_message = Message(id="a1", session_id="s1", role="assistant", content="Existing reply")
    current_user_message = Message(id="u1", session_id="s1", role="user", content="Current turn")
    previous_user_message = Message(id="u0", session_id="s1", role="user", content="Previous turn")

    filtered_history, current_turn_message = split_current_turn_from_history(
        [previous_user_message, current_user_message, assistant_message],
        "u1",
    )

    assert [message.id for message in filtered_history] == ["u0", "a1"]
    assert current_turn_message is current_user_message


def test_prepend_structured_thread_context_skips_minimal_tier() -> None:
    summary_context_msgs = [{"role": "system", "content": "## Summary\nExisting summary"}]

    result = prepend_structured_thread_context(
        summary_context_msgs=summary_context_msgs,
        context_tier="minimal",
        existing_thread_context={"goal": "Ship safely"},
    )

    assert result == summary_context_msgs


def test_prepend_structured_thread_context_adds_rendered_context() -> None:
    summary_context_msgs = [{"role": "system", "content": "## Summary\nExisting summary"}]

    result = prepend_structured_thread_context(
        summary_context_msgs=summary_context_msgs,
        context_tier="standard",
        existing_thread_context={"goal": "Ship safely"},
    )

    assert result[0]["role"] == "system"
    assert result[0]["content"].startswith("## Structured Thread Context\n")
    assert "Ship safely" in result[0]["content"]
    assert result[1:] == summary_context_msgs


def test_build_prompt_messages_preserves_tool_calls_and_trims() -> None:
    history = [
        Message(
            id="a1",
            session_id="s1",
            role="assistant",
            content="Need a tool",
            tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
        ),
        Message(id="t1", session_id="s1", role="tool", content="Tool result"),
    ]
    captured: dict[str, object] = {}

    def trim_messages(messages, budget):
        captured["messages"] = messages
        captured["budget"] = budget
        return messages[:-1]

    result = build_prompt_messages(
        system_prompt_parts=SystemPromptParts((platform_section("System"),)),
        summary_context_msgs=[{"role": "system", "content": "Summary"}],
        history=history,
        current_turn_content="Current turn",
        trim_messages_to_budget=trim_messages,
        token_budget=512,
    )

    assert captured["budget"] == 512
    assert captured["messages"][2]["tool_calls"][0]["function"]["name"] == "lookup"
    assert captured["messages"][-1] == {"role": "user", "content": "Current turn"}
    assert result == captured["messages"][:-1]


def test_build_prompt_messages_marks_stable_and_dynamic_system_prompt_parts() -> None:
    captured: dict[str, object] = {}

    def trim_messages(messages, budget):
        captured["messages"] = messages
        captured["budget"] = budget
        return messages

    parts = SystemPromptParts(
        (platform_section("Platform"), platform_section("\nMode"), authored_section("\n## Agent Blueprint\nAuthored"),
         untrusted_section("\n## Communication Preferences\nShort"), platform_section("\nPrecedence")),
        dynamic="Dynamic",
    )
    result = build_prompt_messages(
        system_prompt_parts=parts,
        summary_context_msgs=[],
        history=[],
        current_turn_content="Current turn",
        trim_messages_to_budget=trim_messages,
        token_budget=512,
    )

    assert captured["budget"] == 512
    assert result[:5] == [
        {"role": "system", "content": "Platform\n\nMode", "cache_scope": "stable",
         "content_trust": "platform_instruction"},
        {"role": "system", "content": "## Agent Blueprint\nAuthored", "cache_scope": "stable",
         "content_trust": "authored"},
        {"role": "system", "content": "## Communication Preferences\nShort", "cache_scope": "stable"},
        {"role": "system", "content": "Precedence", "cache_scope": "stable", "content_trust": "platform_instruction"},
        {"role": "system", "content": "Dynamic", "cache_scope": "volatile"},
    ]
    assert result[-1] == {"role": "user", "content": "Current turn"}
