"""Provider-agnostic inline tool-call recovery (shared by openai_compatible and
bedrock). Covers the Bedrock Claude / Nova malformations that stalled the
"Alice Example" knowledge turn: the models emitted tool calls as text instead of
native tool-call blocks, so nothing executed."""

from __future__ import annotations

import json

from app.agent.providers.inline_tool_calls import parse_inline_tool_calls


def test_anthropic_function_calls_xml_is_recovered():
    # Exact shape Claude Haiku 4.5 on Bedrock emitted (function_calls wrapper,
    # multiple invokes, parameter tags).
    content = (
        "I'll retrieve the required evidence first.\n"
        '<function_calls>\n<invoke name="knowledge_search">\n'
        '<parameter name="query">Alice Example</parameter>\n'
        '<parameter name="limit">20</parameter>\n</invoke>\n</function_calls>\n'
        '<function_calls>\n<invoke name="jira_search">\n'
        '<parameter name="jql">assignee ~ "Alice Example"</parameter>\n</invoke>\n</function_calls>'
    )
    cleaned, calls = parse_inline_tool_calls(content)
    names = [c["function"]["name"] for c in calls]
    assert names == ["knowledge_search", "jira_search"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"query": "Alice Example", "limit": "20"}
    assert "<function_calls>" not in cleaned and "<invoke" not in cleaned


def test_nova_fenced_json_array_is_recovered():
    # Exact shape Amazon Nova on Bedrock emitted: a fenced ```json array of
    # {name, arguments} tool-call objects.
    content = (
        "Let me first check the available knowledge keys.\n"
        '```json\n[\n  {\n    "name": "list_project_knowledge_keys",\n'
        '    "arguments": {}\n  }\n]\n```\n'
    )
    cleaned, calls = parse_inline_tool_calls(content)
    assert calls and calls[0]["function"]["name"] == "list_project_knowledge_keys"
    assert "```" not in cleaned


def test_nova_fenced_array_with_nested_arguments_is_recovered():
    content = (
        '```json\n[{"name": "knowledge_search", "arguments": {"query": "x", "filters": {"team": "devops"}}}]\n```'
    )
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls and json.loads(calls[0]["function"]["arguments"]) == {
        "query": "x",
        "filters": {"team": "devops"},
    }


def test_fenced_json_that_is_not_tool_calls_is_ignored():
    # A fenced JSON array that is plain data (no tool-name-shaped name+arguments)
    # must not be mistaken for tool calls.
    content = '```json\n[{"user": "Alice Example", "role": "DevOps"}]\n```'
    cleaned, calls = parse_inline_tool_calls(content)
    assert calls == []
    assert cleaned == content


def test_tool_tag_with_parameters_is_recovered():
    # MiniMax: <tool name="X"><parameter>...</parameter></tool> inside <tool_call>.
    content = (
        "]<]minimax[>[<tool_call>\n"
        '<tool name="list_project_knowledge_keys">\n</tool>\n'
        '<tool name="knowledge_search">\n<parameter name="query">acme-orders-gitops</parameter>\n</tool>\n'
        "</tool_call>"
    )
    _cleaned, calls = parse_inline_tool_calls(content)
    names = [c["function"]["name"] for c in calls]
    assert names == ["list_project_knowledge_keys", "knowledge_search"]
    assert json.loads(calls[1]["function"]["arguments"]) == {"query": "acme-orders-gitops"}


def test_self_closing_tool_tag_with_attribute_args_is_recovered():
    # MiniMax: self-closing <tool name="X" arg="v" /> — args are the attributes.
    content = (
        "]<]minimax[>[\n<tool_call>\n"
        '<tool name="instruction_get" domain="work_items" workflow_class="backlog_query" />\n'
        "</tool_call>"
    )
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls and calls[0]["function"]["name"] == "instruction_get"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "domain": "work_items",
        "workflow_class": "backlog_query",
    }


def test_colon_json_and_kwargs_forms_are_recovered():
    # MiniMax: `toolname: {json}` and `toolname: key="value"` inside <tool_call>.
    content = '<tool_call>\nknowledge_search: {"query": "Octryx", "top_k": 5}\n</tool_call>'
    _cleaned, calls = parse_inline_tool_calls(content)
    assert calls and json.loads(calls[0]["function"]["arguments"]) == {"query": "Octryx", "top_k": 5}

    content2 = '<tool_call>\nknowledge_search: search_query="Octryx"\n</tool_call>'
    _cleaned2, calls2 = parse_inline_tool_calls(content2)
    assert calls2 and calls2[0]["function"]["name"] == "knowledge_search"
    assert json.loads(calls2[0]["function"]["arguments"]) == {"search_query": "Octryx"}


def test_prose_colon_outside_a_block_is_not_a_tool_call():
    # A plain "word: {...}" in prose (no <tool_call> wrapper) must not fire.
    content = "Summary: the deployment is healthy. Note: check the logs."
    assert parse_inline_tool_calls(content) == (content, [])


def test_plain_prose_passes_through():
    assert parse_inline_tool_calls("Alice is a DevOps engineer.") == (
        "Alice is a DevOps engineer.",
        [],
    )


# Regression: Bedrock Claude Sonnet wrote ```tool_use fences as its final answer.
_SONNET_TOOL_USE_FENCES = (
    "I'll gather the evidence.\n\n"
    '```tool_use\njira_search_issues\n{\n  "jql": "project = OPS",\n  "max_results": 50\n}\n```\n\n'
    '```tool_use\njira_get_project_versions\n{\n  "project_key": "OPS"\n}\n```'
)


def test_sonnet_tool_use_fences_are_recovered_and_stripped():
    cleaned, calls = parse_inline_tool_calls(_SONNET_TOOL_USE_FENCES)
    assert [call["function"]["name"] for call in calls] == ["jira_search_issues", "jira_get_project_versions"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"jql": "project = OPS", "max_results": 50}
    assert cleaned == "I'll gather the evidence."


def test_pseudo_tool_call_names_is_structural():
    from app.agent.providers.inline_tool_calls import pseudo_tool_call_names

    assert pseudo_tool_call_names(_SONNET_TOOL_USE_FENCES) == ["jira_search_issues", "jira_get_project_versions"]
    assert pseudo_tool_call_names('<function_calls><invoke name="knowledge_search"></invoke></function_calls>') == [
        "knowledge_search"
    ]
    assert pseudo_tool_call_names("```tool_use\nnot parseable (\n```") == [""]
    # Quoted material and ordinary answers are not tool calls.
    assert pseudo_tool_call_names('```xml\n<tool_call>{"name": "x", "arguments": {}}</tool_call>\n```') == []
    assert pseudo_tool_call_names('```python\nprint({"name": "x"})\n```\nThe release is out.') == []
    assert pseudo_tool_call_names("OPS 1.2.0 was released on 2026-09-01.") == []


def test_a_repeated_pseudo_tool_call_reply_is_refused():
    import asyncio

    from app.agent.loops.response._loop_pseudo_tool_calls import (
        PSEUDO_TOOL_CALL_REFUSAL_REASON,
        handle_pseudo_tool_call_reply,
    )

    persisted: list[dict] = []

    class _Db:
        async def commit(self):
            return None

    async def persist_traced_assistant_message(**kwargs):
        persisted.append(kwargs)

    async def persist_turn_trace(**_kwargs):
        raise AssertionError("the retry budget is spent: no further reminder")

    outcome = asyncio.run(
        handle_pseudo_tool_call_reply(
            db=_Db(), session_id="s", runtime={"provider_name": "bedrock"}, response={}, request_messages=[],
            messages=[], context_snapshot={}, runtime_attempts=[], runtime_settings={}, usage_model="m",
            content=_SONNET_TOOL_USE_FENCES, tool_calls=None, current_tool_definitions=[],
            consecutive_non_progress_response_count=1, retry_limit=2, persist_turn_trace=persist_turn_trace,
            persist_traced_assistant_message=persist_traced_assistant_message,
        )
    )
    assert outcome["action"] == "return"
    assert "```tool_use" not in outcome["yield_content"]
    assert "No tools were offered" in outcome["yield_content"]
    assert persisted[0]["raw_output"]["refusal_reason"] == PSEUDO_TOOL_CALL_REFUSAL_REASON
    # A normal answer and a reply whose text-derived calls all ran are not refused.
    assert asyncio.run(
        handle_pseudo_tool_call_reply(
            db=_Db(), session_id="s", runtime={}, response={}, request_messages=[], messages=[],
            context_snapshot={}, runtime_attempts=[], runtime_settings={}, usage_model="m",
            content="OPS 1.2.0 is unreleased.", tool_calls=None, current_tool_definitions=[],
            consecutive_non_progress_response_count=0, retry_limit=2, persist_turn_trace=persist_turn_trace,
            persist_traced_assistant_message=persist_traced_assistant_message,
        )
    ) is None


def test_a_reply_whose_recovered_calls_the_audit_rejected_is_a_pseudo_tool_call_reply():
    from app.agent.loops.response._loop_pseudo_tool_calls import pseudo_tool_call_reply

    # The provider stripped the recovered fences; the audit rejected the unknown tool name.
    audited = {"repaired_textual_tool_calls": {"count": 0, "rejected": [{"tool_name": "jira_search_issues"}]}}
    assert pseudo_tool_call_reply("I'll gather the evidence.", None, audited) == ["jira_search_issues"]
    assert pseudo_tool_call_reply("I'll gather the evidence.", None, {}) is None
