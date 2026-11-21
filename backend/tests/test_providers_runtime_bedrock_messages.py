"""Bedrock Converse message shaping (late system messages, tool history) and response parsing."""

from app.agent.providers import BedrockClient


def test_bedrock_converse_kwargs_converts_late_system_messages_to_user_context():
    client = BedrockClient(region="eu-central-1", config_json={"prompt_caching": {"enabled": False}})

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform contract."},
            {"role": "user", "content": "Who is Alice Example?"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1", "function": {"name": "search_jira_users", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": '{"total": 1}'},
            {"role": "system", "content": "Use evidence only."},
            {"role": "user", "content": "Produce the final answer now."},
        ],
        model="amazon.nova-2-lite-v1:0",
        tools=None,
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is False
    assert kwargs["system"] == [{"text": "Stable platform contract."}]
    assert kwargs["messages"][0]["role"] == "user"
    assert any(
        block.get("text", "").startswith("System context update:\nUse evidence only.")
        for message in kwargs["messages"]
        for block in message.get("content", [])
    )
    assert kwargs["messages"][-1]["role"] == "user"


def test_bedrock_converse_kwargs_collapses_source_evidence_final_answer_to_fresh_user_turn():
    client = BedrockClient(region="eu-central-1", config_json={"prompt_caching": {"enabled": False}})

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform contract."},
            {"role": "user", "content": "Who is Alice Example?"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1", "function": {"name": "search_jira_users", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": '{"total": 1}'},
            {"role": "system", "content": "[source_evidence_final_answer]\nEvidence summary: Jira and Knowledge matched."},
            {"role": "user", "content": "Produce the final answer now."},
            {"role": "system", "content": "## Turn Working Summary\nKnowledge matched 10 entries."},
        ],
        model="amazon.nova-2-lite-v1:0",
        tools=None,
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is False
    assert kwargs["system"] == [{"text": "Stable platform contract."}]
    assert kwargs["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "text": (
                        "[source_evidence_final_answer]\nEvidence summary: Jira and Knowledge matched.\n\n"
                        "Produce the final answer now.\n\n## Turn Working Summary\nKnowledge matched 10 entries."
                    )
                }
            ],
        }
    ]


def test_bedrock_converse_kwargs_flattens_tool_history_without_current_tools():
    client = BedrockClient(region="eu-central-1")

    kwargs, _ = client._build_converse_kwargs(
        messages=[
            {"role": "user", "content": "Create topology"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "tool-1",
                        "type": "function",
                        "function": {"name": "create_diagram", "arguments": '{"title": "Topology"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "tool-1", "content": '{"status": "created"}'},
            {"role": "user", "content": "Summarize the result"},
        ],
        model="amazon.nova-2-lite-v1:0",
        tools=None,
        temperature=0,
        max_tokens=512,
    )

    assert "toolConfig" not in kwargs
    serialized_messages = str(kwargs["messages"])
    assert "toolUse" not in serialized_messages
    assert "toolResult" not in serialized_messages
    assert "Tool request create_diagram" in serialized_messages
    assert "Tool result tool-1" in serialized_messages


def test_bedrock_parse_response_normalizes_converse_usage_and_model():
    client = BedrockClient(region="eu-central-1")

    result = client._parse_response(
        {
            "output": {
                "message": {
                    "content": [
                        {"text": "ok"},
                    ]
                }
            },
            "usage": {
                "inputTokens": 123,
                "outputTokens": 45,
                "totalTokens": 180,
                "cacheReadInputTokens": 12,
                "cacheWriteInputTokens": 0,
            },
            "metrics": {},
        },
        fallback_model="anthropic.claude-sonnet-4-6",
        prompt_cache_enabled=True,
    )

    assert result["content"] == "ok"
    assert result["model"] == "anthropic.claude-sonnet-4-6"
    assert result["usage"] == {
        "prompt_tokens": 135,
        "completion_tokens": 45,
        "total_tokens": 180,
        "inputTokens": 123,
        "outputTokens": 45,
        "totalTokens": 180,
        "bedrock_input_tokens_non_cached": 123,
        "bedrock_prompt_cache_enabled": True,
        "cacheReadInputTokens": 12,
        "cacheWriteInputTokens": 0,
        "bedrock_cache_read_input_tokens": 12,
        "bedrock_cache_write_input_tokens": 0,
        "bedrock_total_input_tokens": 135,
    }
