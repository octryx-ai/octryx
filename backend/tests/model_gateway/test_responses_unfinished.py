"""Both public Responses endpoints (``/openai`` governed and the Codex seat) with unfinished and unknown content.

The routes forward the client's own Responses body unchanged or refuse it (the gateway changes nothing): an
unfinished newest turn, an unfinished re-sent call output and call arguments too wide to examine are refused
(``content_scan_unfinished``); a part type the gateway does not know is read like any other part of the body (a
credential in it is refused); a reasoning summary is examined like text while its encrypted content is opaque state
forwarded as it is. Each property is asserted at both public endpoints.
"""

from __future__ import annotations

import json

import pytest

from tests.model_gateway import codex_seat_support
from tests.model_gateway import model_gateway_openai_responses_support as openai_support
from tests.model_gateway.codex_seat_support import _codex_session, _headers, _reason, chatgpt  # noqa: F401
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.model_gateway_openai_responses_support import responses_setup  # noqa: F401

from .test_inbound_anthropic_gateway import AWS_KEY_LOOKALIKE

# Credential assignments (a gateway kind, C12F-08) past a detector's candidate limit: the scan cannot finish.
FRAGMENT = "password=Value0x"
UNFINISHED = " ".join(f"password=Value{index}x" for index in range(5200))
# More internal-address candidates than a detector examines in one call's arguments.
WIDE = {f"host_{index}": f"password=Wide{index}x" for index in range(5200)}


def _history(body: dict, output: str) -> dict:
    """``body`` whose history call output is ``output``, followed by an assistant message the client wrote."""
    items = list(body["input"])
    outputs = [index for index, item in enumerate(items) if item.get("type") == "function_call_output"]
    items[outputs[0]] = {**items[outputs[0]], "output": output}
    items.insert(-1, {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Ok."}]})
    return {**body, "input": items}


def _wide(body: dict) -> dict:
    body = _history(body, "3 passed")
    for item in body["input"]:
        if item.get("type") == "function_call":
            item["arguments"] = json.dumps(WIDE)
    return body


def _unknown_part(body: dict) -> dict:
    body["input"][-1]["content"].append({"type": "input_custom", "payload": f"key {AWS_KEY_LOOKALIKE}"})
    return body


def _summary(body: dict, text: str = "ran the tests") -> dict:
    body = _history(body, "3 passed")
    call = next(index for index, item in enumerate(body["input"]) if item.get("type") == "function_call")
    body["input"] = [item for item in body["input"] if item.get("type") != "reasoning"]
    body["input"].insert(call, {"type": "reasoning", "id": "rs_1", "encrypted_content": f"opaque {AWS_KEY_LOOKALIKE}",
                                "summary": [{"type": "summary_text", "text": text}]})
    return body


REFUSED = {
    "unfinished-newest-turn": (lambda body: {**body, "input": [*body["input"][:-1], {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": UNFINISHED}]}]},
        "content_scan_unfinished"),
    "unfinished-re-sent-output": (lambda body: _history(body, UNFINISHED), "content_scan_unfinished"),
    "arguments-too-wide-to-examine": (_wide, "content_scan_unfinished"),
    "credential-in-an-unknown-part-type": (_unknown_part, "secret_detected_in_prompt"),
    "credential-in-a-reasoning-summary": (lambda body: _summary(body, f"key {AWS_KEY_LOOKALIKE}"),
                                          "secret_detected_in_prompt"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(REFUSED))
async def test_openai_refuses(client, responses_setup, name):  # noqa: F811
    fake, build = responses_setup
    mutate, reason = REFUSED[name]
    response = await client.post(openai_support.ROUTE, json=mutate(openai_support._body()), headers=await build())
    assert response.status_code == 400 and response.json()["error"]["code"] == reason, response.text
    assert fake.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(REFUSED))
async def test_the_codex_seat_refuses(client, db, chatgpt, name):  # noqa: F811
    _workspace_id, _user, gateway, credential = await _codex_session(client, db)
    mutate, reason = REFUSED[name]
    response = await client.post(codex_seat_support.ROUTE, json=mutate(codex_seat_support._body()),
                                 headers=_headers(gateway, credential))
    assert (response.status_code, _reason(response)) == (400, reason), response.text
    assert chatgpt.requests == []


@pytest.mark.asyncio
async def test_openai_examines_reasoning_summaries_and_forwards_encrypted_state_unchanged(client, responses_setup):  # noqa: F811
    fake, build = responses_setup
    body = _summary(openai_support._body())
    response = await client.post(openai_support.ROUTE, json=body, headers=await build())
    assert response.status_code == 200, response.text
    (sent,) = fake.requests
    assert json.loads(sent.content)["input"] == body["input"], "nothing is changed on the gateway"


@pytest.mark.asyncio
async def test_the_codex_seat_forwards_reasoning_and_encrypted_state_unchanged(client, db, chatgpt):  # noqa: F811
    _workspace_id, _user, gateway, credential = await _codex_session(client, db)
    body = _summary(codex_seat_support._body())
    response = await client.post(codex_seat_support.ROUTE, json=body, headers=_headers(gateway, credential))
    assert response.status_code == 200, response.text
    (sent,) = chatgpt.requests
    assert json.loads(sent.content)["input"] == body["input"]
