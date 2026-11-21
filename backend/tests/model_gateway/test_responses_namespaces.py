"""Codex's namespace tools flattened for any upstream and mapped back."""

from __future__ import annotations

from app.services.model_gateway.inbound.responses_namespaces import MAX_TOOL_NAME, flat_name, flatten_request

NS = "mcp__octryx_knowledge"
BODY = {
    "model": "alias", "tools": [
        {"type": "function", "name": "shell", "parameters": {"type": "object"}},
        {"type": "namespace", "name": NS, "description": "Tools in the namespace.", "tools": [
            {"type": "function", "name": "workflow_catalog", "description": "List workflows.", "strict": False,
             "defer_loading": True, "parameters": {"type": "object", "properties": {}}}]}],
    "input": [
        {"type": "function_call", "namespace": NS, "name": "workflow_catalog", "call_id": "c1", "arguments": "{}"},
        {"type": "function_call_output", "namespace": NS, "call_id": "c1", "output": "3 workflows"},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Next?"}]}],
}


def test_namespace_tools_become_plain_tools_and_calls_get_their_namespace_back():
    upstream, names = flatten_request(BODY)
    assert [tool["name"] for tool in upstream["tools"]] == ["shell", f"{NS}__workflow_catalog"]
    flat = upstream["tools"][1]
    assert flat["type"] == "function" and "defer_loading" not in flat and flat["description"] == "List workflows."
    call, output = upstream["input"][0], upstream["input"][1]
    assert call["name"] == f"{NS}__workflow_catalog" and "namespace" not in call
    assert "namespace" not in output and upstream["input"][2] == BODY["input"][2]
    assert BODY["tools"][1]["type"] == "namespace"  # the client's body stays as it was sent

    item = {"type": "function_call", "name": f"{NS}__workflow_catalog", "call_id": "c2", "arguments": "{}"}
    event = names.restore_payload({"type": "response.output_item.done", "item": item})
    assert event["item"]["namespace"] == NS and event["item"]["name"] == "workflow_catalog"
    done = names.restore_payload({"type": "response.completed", "response": {"output": [item]}})
    assert done["response"]["output"][0]["namespace"] == NS
    plain = {"type": "function_call", "name": "shell", "call_id": "c3", "arguments": "{}"}
    untouched = {"type": "response.output_item.done", "item": plain}
    assert names.restore_payload(untouched) is untouched


def test_a_long_name_is_shortened_stably_within_the_limit():
    long = flat_name("mcp__" + "x" * 60, "tool")
    assert len(long) == MAX_TOOL_NAME and long == flat_name("mcp__" + "x" * 60, "tool")
    assert flatten_request({"model": "m", "input": "hi"})[1].pairs == {}
