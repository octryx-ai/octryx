"""Both public Responses relays read the whole request they forward (owner decision 24.11.).

``/openai`` (governed, LiteLLM upstream) and the Codex seat (ChatGPT upstream) forward the client's own Responses
body, so the gateway's scan (``content_routing.gateway``) reads that body as one text, never the governance view: the
tool declarations (names, descriptions, parameter schemas, a namespace's inner tools), the response-format
configuration, every field of a part, re-sent history (call outputs, readable reasoning fields). Only the values
under the opaque key list are not read — by key, wherever they are, without validating their content (README
"Sensitive content handling": the threat model is accidental leakage, not a deliberately evasive client).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from tests.model_gateway import codex_seat_support
from tests.model_gateway import model_gateway_openai_responses_support as openai_support
from tests.model_gateway.codex_seat_support import _codex_session, _headers, _reason, chatgpt  # noqa: F401
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.model_gateway_openai_responses_support import responses_setup  # noqa: F401

from .test_inbound_anthropic_gateway import AWS_KEY_LOOKALIKE

SECRET_TEXT = f"use key {AWS_KEY_LOOKALIKE}"
# Credential assignments (a gateway kind, C12F-08) past a detector's candidate limit: the scan cannot finish.
UNFINISHED = " ".join(f"password=Value{index}x" for index in range(5200))
SECRET = "secret_detected_in_prompt"
UNFINISHED_SCAN = "content_scan_unfinished"


def _tool_description(body: dict[str, Any]) -> None:
    body["tools"][0]["description"] = SECRET_TEXT


def _namespace_tool(body: dict[str, Any]) -> None:
    body["tools"].append({"type": "namespace", "name": "mcp__kb", "description": "Knowledge base.",
                          "tools": [{"type": "function", "name": "lookup", "description": SECRET_TEXT}]})


def _parameter_schema(body: dict[str, Any]) -> None:
    body["tools"][0]["parameters"] = {"type": "object", "properties": {
        "region": {"type": "string", "default": AWS_KEY_LOOKALIKE}}}


def _response_format(body: dict[str, Any]) -> None:
    body["text"] = {"format": {"type": "json_schema", "name": "answer", "strict": True, "schema": {
        "type": "object", "properties": {"key": {"type": "string", "description": SECRET_TEXT}}}}}


def _unfinished_tool(body: dict[str, Any]) -> None:
    body["tools"][0]["description"] = UNFINISHED


def _opaque_key_in_a_readable_part(body: dict[str, Any]) -> None:
    body["input"][-1]["content"].append({"type": "input_text", "text": "See the note.",
                                         "encrypted_content": SECRET_TEXT})


def _opaque_key_in_an_unknown_item(body: dict[str, Any]) -> None:
    body["input"].append({"type": "note", "id": "n_1", "encrypted_content": SECRET_TEXT})


def _nested_reasoning_shape(body: dict[str, Any]) -> None:
    body["input"][-1]["content"].append({"type": "input_custom", "payload": {
        "type": "reasoning", "encrypted_content": SECRET_TEXT}})


def _history_part_field(body: dict[str, Any]) -> None:
    body["input"][0]["content"][0]["note"] = SECRET_TEXT


def _history_call_output(body: dict[str, Any]) -> None:
    next(item for item in body["input"] if item.get("type") == "function_call_output")["output"] = SECRET_TEXT


def _history_call_arguments(body: dict[str, Any]) -> None:
    next(item for item in body["input"] if item.get("type") == "function_call")["arguments"] = json.dumps(
        {"command": ["deploy", AWS_KEY_LOOKALIKE]})


def _reasoning_summary(body: dict[str, Any]) -> None:
    call = next(index for index, item in enumerate(body["input"]) if item.get("type") == "function_call")
    body["input"].insert(call, {"type": "reasoning", "id": "rs_2", "encrypted_content": "opaque",
                                "summary": [{"type": "summary_text", "text": SECRET_TEXT}]})


def _extra_top_level_field(body: dict[str, Any]) -> None:
    body["metadata"] = {"note": SECRET_TEXT}


REFUSED: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "tool-description": (_tool_description, SECRET),
    "namespace-tool-description": (_namespace_tool, SECRET),
    "parameter-schema": (_parameter_schema, SECRET),
    "response-format-schema": (_response_format, SECRET),
    "unfinished-tool-description": (_unfinished_tool, UNFINISHED_SCAN),
    "history-part-field": (_history_part_field, SECRET),
    "history-call-output": (_history_call_output, SECRET),
    "history-call-arguments": (_history_call_arguments, SECRET),
    "history-reasoning-summary": (_reasoning_summary, SECRET),
    "extra-top-level-field": (_extra_top_level_field, SECRET),
}
#: The opaque key list applies by key alone, wherever the key is: these are forwarded unread (no validation).
OPAQUE_BY_KEY: dict[str, Callable[[dict[str, Any]], None]] = {
    "opaque-key-in-a-readable-part": _opaque_key_in_a_readable_part,
    "opaque-key-in-an-unknown-item": _opaque_key_in_an_unknown_item,
    "reasoning-shape-nested-in-a-part": _nested_reasoning_shape,
}
# Opaque provider state: a top-level reasoning item in the history and a compaction item in the newest turn.
OPAQUE = f"gAAAAB{AWS_KEY_LOOKALIKE}opaque"


def _with_opaque_state(body: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in body["input"] if item.get("type") != "reasoning"]
    call = next(index for index, item in enumerate(items) if item.get("type") == "function_call")
    items.insert(call, {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": OPAQUE})
    items.insert(len(items) - 1, {"type": "compaction", "id": "cmp_1", "encrypted_content": OPAQUE})
    return {**body, "input": items}


def _case(body: dict[str, Any], name: str) -> tuple[dict[str, Any], str]:
    mutate, reason = REFUSED[name]
    changed = json.loads(json.dumps(body))
    mutate(changed)
    return changed, reason


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(REFUSED))
async def test_openai_refuses_a_forwarded_field_with_a_secret_or_an_unfinished_scan(client, responses_setup,  # noqa: F811
                                                                                   name):
    fake, build = responses_setup
    body, reason = _case(openai_support._body(), name)
    response = await client.post(openai_support.ROUTE, json=body, headers=await build())
    assert response.status_code == 400 and response.json()["error"]["code"] == reason, response.text
    assert fake.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(REFUSED))
async def test_the_codex_seat_refuses_a_forwarded_field_with_a_secret_or_an_unfinished_scan(client, db, chatgpt,  # noqa: F811
                                                                                           name):
    _workspace_id, _user, gateway, credential = await _codex_session(client, db)
    body, reason = _case(codex_seat_support._body(), name)
    response = await client.post(codex_seat_support.ROUTE, json=body, headers=_headers(gateway, credential))
    assert (response.status_code, _reason(response)) == (400, reason), response.text
    assert chatgpt.requests == []


@pytest.mark.asyncio
async def test_openai_forwards_opaque_reasoning_and_compaction_state(client, responses_setup):  # noqa: F811
    fake, build = responses_setup
    response = await client.post(openai_support.ROUTE, json=_with_opaque_state(openai_support._body()),
                                 headers=await build())
    assert response.status_code == 200, response.text
    (sent,) = fake.requests
    items = json.loads(sent.content)["input"]
    assert {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": OPAQUE} in items
    assert {"type": "compaction", "id": "cmp_1", "encrypted_content": OPAQUE} in items


@pytest.mark.asyncio
async def test_the_codex_seat_forwards_opaque_reasoning_and_compaction_state(client, db, chatgpt):  # noqa: F811
    _workspace_id, _user, gateway, credential = await _codex_session(client, db)
    response = await client.post(codex_seat_support.ROUTE, json=_with_opaque_state(codex_seat_support._body()),
                                 headers=_headers(gateway, credential))
    assert response.status_code == 200, response.text
    (sent,) = chatgpt.requests
    items = json.loads(sent.content)["input"]
    assert {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": OPAQUE} in items
    assert {"type": "compaction", "id": "cmp_1", "encrypted_content": OPAQUE} in items


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(OPAQUE_BY_KEY))
async def test_openai_forwards_an_opaque_key_wherever_it_is(client, responses_setup, name):  # noqa: F811
    fake, build = responses_setup
    body = json.loads(json.dumps(openai_support._body()))
    OPAQUE_BY_KEY[name](body)
    response = await client.post(openai_support.ROUTE, json=body, headers=await build())
    assert response.status_code == 200, response.text
    (sent,) = fake.requests
    assert json.loads(sent.content)["input"] == body["input"]
