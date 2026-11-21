"""Bedrock client credentials and Converse cache points, cache TTLs and tool definition ordering."""

from app.agent.providers import BedrockClient


def test_bedrock_client_builds_static_credential_kwargs():
    client = BedrockClient(
        region="eu-central-1",
        aws_access_key_id="access-key",
        aws_secret_access_key="secret-key",
        aws_session_token="session-token",
    )

    assert client._aws_client_kwargs() == {
        "region_name": "eu-central-1",
        "aws_access_key_id": "access-key",
        "aws_secret_access_key": "secret-key",
        "aws_session_token": "session-token",
    }


def test_bedrock_converse_kwargs_adds_cache_points_for_supported_model():
    client = BedrockClient(
        region="eu-central-1",
        config_json={"prompt_caching": {"enabled": True, "min_tokens": 1}},
    )

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform instructions."},
            {"role": "user", "content": "Inspect AWS state."},
        ],
        model="anthropic.claude-sonnet-4-6",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "aws_read_operation",
                    "description": "Read AWS state.",
                    "parameters": {"type": "object", "properties": {"service": {"type": "string"}}},
                },
            }
        ],
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is True
    assert kwargs["system"][-1] == {"cachePoint": {"type": "default"}}
    assert kwargs["toolConfig"]["tools"][-1] == {"cachePoint": {"type": "default"}}


def test_bedrock_converse_kwargs_adds_cache_points_for_nova_lite():
    client = BedrockClient(
        region="eu-central-1",
        config_json={"prompt_caching": {"enabled": True, "min_tokens": 1}},
    )

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform instructions."},
            {"role": "user", "content": "Inspect AWS state."},
        ],
        model="amazon.nova-2-lite-v1:0",
        tools=None,
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is True
    assert kwargs["system"][-1] == {"cachePoint": {"type": "default"}}


def test_bedrock_converse_kwargs_omits_extended_ttl_for_nova_lite():
    client = BedrockClient(
        region="eu-central-1",
        config_json={"prompt_caching": {"enabled": True, "min_tokens": 1, "ttl": "1h"}},
    )

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform instructions."},
            {"role": "user", "content": "Inspect AWS state."},
        ],
        model="amazon.nova-2-lite-v1:0",
        tools=None,
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is True
    assert kwargs["system"][-1] == {"cachePoint": {"type": "default"}}


def test_bedrock_converse_kwargs_skips_tool_cache_point_for_nova_lite():
    client = BedrockClient(
        region="eu-central-1",
        config_json={"prompt_caching": {"enabled": True, "min_tokens": 1, "ttl": "1h"}},
    )

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform instructions."},
            {"role": "user", "content": "Inspect AWS state."},
        ],
        model="amazon.nova-2-lite-v1:0",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "aws_read_operation",
                    "description": "Read AWS state.",
                    "parameters": {"type": "object", "properties": {"service": {"type": "string"}}},
                },
            }
        ],
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is True
    assert kwargs["system"][-1] == {"cachePoint": {"type": "default"}}
    assert kwargs["toolConfig"]["tools"][-1] != {"cachePoint": {"type": "default"}}


def test_bedrock_converse_kwargs_keeps_extended_ttl_for_anthropic():
    client = BedrockClient(
        region="eu-central-1",
        config_json={"prompt_caching": {"enabled": True, "min_tokens": 1, "ttl": "1h"}},
    )

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform instructions."},
            {"role": "user", "content": "Inspect AWS state."},
        ],
        model="anthropic.claude-haiku-4-5-20251001-v1:0",
        tools=None,
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is True
    assert kwargs["system"][-1] == {"cachePoint": {"type": "default", "ttl": "1h"}}


def test_bedrock_converse_kwargs_caches_only_stable_system_prefix():
    client = BedrockClient(
        region="eu-central-1",
        config_json={"prompt_caching": {"enabled": True, "min_tokens": 1}},
    )

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform contract.", "cache_scope": "stable"},
            {"role": "system", "content": "Volatile session workspace.", "cache_scope": "volatile"},
            {"role": "user", "content": "Inspect AWS state."},
        ],
        model="amazon.nova-2-lite-v1:0",
        tools=None,
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is True
    assert kwargs["system"] == [
        {"text": "Stable platform contract."},
        {"cachePoint": {"type": "default"}},
        {"text": "Volatile session workspace."},
    ]


def test_bedrock_converse_kwargs_skips_cache_points_for_unsupported_model():
    client = BedrockClient(
        region="eu-central-1",
        config_json={"prompt_caching": {"enabled": True, "min_tokens": 1}},
    )

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform instructions."},
            {"role": "user", "content": "Inspect AWS state."},
        ],
        model="anthropic.claude-3-haiku-20240307-v1:0",
        tools=None,
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is False
    assert kwargs["system"] == [{"text": "Stable platform instructions."}]


def test_bedrock_converse_kwargs_strips_cache_scope_for_unsupported_model():
    client = BedrockClient(
        region="eu-central-1",
        config_json={"prompt_caching": {"enabled": True, "min_tokens": 1}},
    )

    kwargs, cache_enabled = client._build_converse_kwargs(
        messages=[
            {"role": "system", "content": "Stable platform instructions.", "cache_scope": "stable"},
            {"role": "system", "content": "Dynamic context.", "cache_scope": "volatile"},
            {"role": "user", "content": "Inspect AWS state."},
        ],
        model="anthropic.claude-3-haiku-20240307-v1:0",
        tools=None,
        temperature=0,
        max_tokens=1024,
    )

    assert cache_enabled is False
    assert kwargs["system"] == [
        {"text": "Stable platform instructions."},
        {"text": "Dynamic context."},
    ]


def test_bedrock_converse_kwargs_sorts_tool_definitions_for_cache_stability():
    client = BedrockClient(
        region="eu-central-1",
        config_json={"prompt_caching": {"enabled": False}},
    )

    kwargs, _ = client._build_converse_kwargs(
        messages=[{"role": "user", "content": "Inspect AWS state."}],
        model="amazon.nova-2-lite-v1:0",
        tools=[
            {"type": "function", "function": {"name": "z_tool", "description": "Z"}},
            {"type": "function", "function": {"name": "a_tool", "description": "A"}},
        ],
        temperature=0,
        max_tokens=1024,
    )

    assert [tool["toolSpec"]["name"] for tool in kwargs["toolConfig"]["tools"]] == ["a_tool", "z_tool"]
