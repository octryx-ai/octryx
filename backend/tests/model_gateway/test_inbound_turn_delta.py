"""Contract: the newest turn is everything after the last assistant message (live Claude Code 2.1 shape)."""

from app.services.model_gateway.inbound.turn_delta import newest_turn, scanned_texts

_AWS_ID = "AKIA" + "IOSFODNN7EXAMPLE"


def _claude_code_request() -> dict:
    return {
        "system": [{"type": "text", "text": "You are Claude Code."}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Add sub() to calc.py"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Editing."},
                    {"type": "tool_use", "id": "toolu_1", "name": "Edit", "input": {"file_path": "calc.py"}},
                ],
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "updated"}]},
            # Claude Code 2.1 appends a system-role message after the user turn.
            {"role": "system", "content": f"<system-reminder>env {_AWS_ID}</system-reminder>"},
        ],
    }


def test_trailing_system_message_does_not_hide_the_turn():
    delta = newest_turn(_claude_code_request()["messages"])
    assert [(use.tool_use_id, use.name, use.block_index) for use in delta.prior_tool_uses] == [("toolu_1", "Edit", 1)]
    assert [(result.tool_use_id, result.is_error, result.text) for result in delta.tool_results] == [
        ("toolu_1", False, "updated")
    ]
    assert delta.user_texts == ()


def test_inline_system_text_is_scanned_but_is_not_the_users_words():
    body = _claude_code_request()
    assert any(_AWS_ID in text for text in scanned_texts(body))
    assert newest_turn(body["messages"]).user_texts == ()


def test_first_call_without_assistant_takes_the_whole_prompt():
    delta = newest_turn([{"role": "user", "content": "hello"}, {"role": "system", "content": "reminder"}])
    assert delta.user_texts == ("hello",)
    assert delta.inline_system_texts == ("reminder",)
    assert delta.prior_tool_uses == ()
