from app.services.token_estimation import estimate_message_tokens, estimate_serialized_tokens


def test_estimate_serialized_tokens_penalizes_dense_structured_payloads() -> None:
    natural_language = {"summary": "deployments are healthy and capacity remains stable across the cluster"}
    structured_payload = {
        "files": [
            {
                "path": f"services/api/module_{index}/handler.py",
                "diff": "if(value!=None){return map_items(items[index]['key_name'])};" * 4,
            }
            for index in range(8)
        ]
    }

    assert estimate_serialized_tokens(structured_payload) > estimate_serialized_tokens(natural_language)


def test_estimate_serialized_tokens_accounts_for_non_ascii_pressure() -> None:
    ascii_payload = {"summary": "status ok " * 20}
    unicode_payload = {"summary": "分析完了です。例外はありません。" * 20}

    assert estimate_serialized_tokens(unicode_payload) > estimate_serialized_tokens(ascii_payload)


def test_estimate_message_tokens_adds_tool_call_overhead() -> None:
    plain_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "inspect the service"},
    ]
    tool_messages = [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-a", "function": {"name": "todo_read", "arguments": '{"id":1}'}},
                {"id": "call-b", "function": {"name": "todo_read", "arguments": '{"id":2}'}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-a", "content": '{"result":"ok"}'},
        {"role": "tool", "tool_call_id": "call-b", "content": '{"result":"ok"}'},
        {"role": "user", "content": "continue"},
    ]

    assert estimate_message_tokens(tool_messages) > estimate_message_tokens(plain_messages)


def test_estimate_serialized_tokens_accepts_broad_model_family_hints() -> None:
    payload = {"tool_calls": [{"name": "run", "arguments": {"path": "src/example/really_long_identifier_name.ts"}}]}

    hinted = estimate_serialized_tokens(payload, provider_name="copilot", model_id="gpt-5")
    generic = estimate_serialized_tokens(payload)

    assert hinted >= generic
