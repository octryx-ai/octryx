from __future__ import annotations

import json

from app.agent.providers.inline_tool_calls import parse_inline_tool_calls


def test_inline_json_tool_call_is_recovered():
    content = (
        '<tool_call>\n{"name": "commit_and_push_repository_branch", '
        '"arguments": {"local_path": ".", "branch_name": "feature/x"}}\n</tool_call>'
    )
    cleaned, calls = parse_inline_tool_calls(content)
    assert cleaned == ""
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "commit_and_push_repository_branch"
    assert json.loads(calls[0]["function"]["arguments"])["branch_name"] == "feature/x"


def test_provider_stream_markers_are_stripped_before_parsing():
    content = (
        "I'll proceed.]<]minimax[>[<tool_call>\n]<]minimax[>["
        '{"name": "get_git_diff", "arguments": {}}]<]minimax[>[</tool_call>'
    )
    cleaned, calls = parse_inline_tool_calls(content)
    assert calls and calls[0]["function"]["name"] == "get_git_diff"
    assert "tool_call" not in cleaned


def test_plain_content_and_invalid_json_pass_through():
    assert parse_inline_tool_calls("just prose") == ("just prose", [])
    content = "<tool_call>not json</tool_call>"
    cleaned, calls = parse_inline_tool_calls(content)
    assert calls == []
    assert cleaned == content


def test_invoke_xml_inside_tool_call_with_markers_is_recovered():
    # Exact shape from a failing MiniMax-M3 session: <tool_call><invoke .../> with
    # provider stream markers scattered between tokens. Must still run the tool.
    content = (
        "]<]minimax[>[<tool_call>\n]<]minimax[>["
        '<invoke name="list_project_knowledge_keys">]<]minimax[>[</invoke>\n'
        "]<]minimax[>[</tool_call>"
    )
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls and calls[0]["function"]["name"] == "list_project_knowledge_keys"


def test_invoke_parameters_are_recovered_as_arguments():
    content = '<tool_call><invoke name="knowledge_search"><parameter name="query">Alice</parameter></invoke></tool_call>'
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls and json.loads(calls[0]["function"]["arguments"]) == {"query": "Alice"}


def test_bare_json_tool_call_without_wrapper_is_recovered():
    content = 'Let me confirm what is available.\n{\n  "name": "list_project_knowledge_keys",\n  "arguments": {}\n}'
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls and calls[0]["function"]["name"] == "list_project_knowledge_keys"


def test_json_object_that_is_not_a_tool_name_is_not_recovered():
    # A normal answer that happens to contain a name/arguments object must not
    # be mistaken for a tool call (name is not a tool-name identifier).
    content = 'Example: {"name": "Alice Example", "arguments": {"role": "devops"}}'
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls == []


def test_multiple_name_json_calls_in_one_block_are_recovered():
    # Exact shape from a failing MiniMax-M3 session: several "toolname {json}"
    # lines with // comments inside a single <tool_call> block.
    content = (
        "Let me retry.]<]minimax[>[<tool_call>\n"
        ' list_project_knowledge_keys {"max_keys": 200} // Retry: list keys\n'
        ' knowledge_search {"query": "Alice Example", "top_k": 10} // targeted search\n'
        "</tool_call>"
    )
    _cleaned, calls = parse_inline_tool_calls(content)
    names = [c["function"]["name"] for c in calls]
    assert names == ["list_project_knowledge_keys", "knowledge_search"]
    assert json.loads(calls[1]["function"]["arguments"]) == {"query": "Alice Example", "top_k": 10}
