"""Contract tests for the inbound OpenAI Responses gateway (Codex through the launcher).

The platform route runs in-process; LiteLLM is an ``httpx.MockTransport`` that records every request, so a
refusal is proven to dispatch *nothing*. Identity, admission and budget are the Anthropic route's steps; these
tests prove the ``/openai`` surface runs them and answers in the OpenAI shape.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.models import Message, ToolCall, TurnTrace, UsageEvent
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.model_gateway_openai_responses_support import (  # noqa: F401
    CODEX_SESSION,
    ROUTE,
    USAGE,
    _body,
    _response,
    _sse,
    responses_setup,
)

from .conftest import ALIAS, MODEL_GROUP, VIRTUAL_KEY

MODELS_ROUTE = "/api/v1/model-gateway/openai/v1/models"


async def test_streamed_call_is_relayed_under_the_alias_and_recorded(client, db, responses_setup):  # noqa: F811
    fake, build = responses_setup

    response = await client.post(ROUTE, json=_body(), headers=await build())

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert f'"model":"{ALIAS}"' in response.text and MODEL_GROUP not in response.text
    assert '"delta": "pass."' in response.text and "response.completed" in response.text
    [sent] = fake.requests
    assert sent.url.path == "/v1/responses"
    forwarded = json.loads(sent.content)
    assert forwarded["model"] == MODEL_GROUP and forwarded["input"] == _body()["input"]
    assert sent.headers["authorization"] == f"Bearer {VIRTUAL_KEY}"
    assert "x-octryx-session" not in sent.headers and "session-id" not in sent.headers

    [usage] = (await db.execute(select(UsageEvent).where(UsageEvent.model == ALIAS))).scalars().all()
    assert (usage.tokens_in, usage.tokens_out, usage.cache_read_tokens) == (1000, 500, 200)
    # Catalog pricing over all prompt tokens: (1200 * 1.0 + 500 * 2.0) / 1e6.
    assert Decimal(str(usage.cost)) == Decimal("0.002200")
    assert usage.request_id == "req_up_1"

    [call] = (await db.execute(select(ToolCall).where(ToolCall.session_id == usage.session_id))).scalars().all()
    assert (call.request_id, call.tool_name, call.status) == ("call_1", "Bash", "success")  # Codex shell -> Bash
    assert call.result == {"is_error": False, "excerpt": "3 passed"}
    messages = (await db.execute(select(Message).where(Message.session_id == usage.session_id))).scalars().all()
    assert sorted((item.role, item.content) for item in messages) == [
        ("assistant", "All tests pass."), ("user", "Now summarize.")]
    [trace] = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == usage.session_id))).scalars().all()
    assert trace.usage_json["stream_completed"] is True and trace.usage_json["stop_reason"] == "end_turn"
    assert trace.context_snapshot_json["codex_session_id"] == CODEX_SESSION


async def test_non_streaming_answer_is_rewritten_and_observed(client, db, responses_setup):  # noqa: F811
    fake, build = responses_setup

    response = await client.post(ROUTE, json=_body(stream=False), headers=await build())

    assert response.status_code == 200, response.text
    assert response.json()["model"] == ALIAS
    [trace] = (await db.execute(select(TurnTrace))).scalars().all()
    assert trace.usage_json["stop_reason"] == "tool_use"
    assert trace.raw_output["tool_uses"] == [{"id": "call_9", "name": "Bash"}]


async def test_models_lists_the_admitted_aliases_in_the_openai_shape(client, responses_setup):  # noqa: F811
    _fake, build = responses_setup

    response = await client.get(MODELS_ROUTE, headers=await build())

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["object"] == "list"
    assert [(row["id"], row["object"]) for row in page["data"]] == [(ALIAS, "model")]


async def test_an_upstream_naming_the_model_only_at_the_end_is_held_checked_then_relayed(client, responses_setup):  # noqa: F811
    """llama.cpp's server names the model only in ``response.completed``: nothing goes out before it is checked."""
    fake, build = responses_setup
    fake.model_in_created = False
    headers = await build()

    answered = await client.post(ROUTE, json=_body(), headers=headers)
    assert answered.status_code == 200, answered.text
    events = [json.loads(line[6:]) for line in answered.text.splitlines() if line.startswith("data: ")]
    assert [event["type"] for event in events][0] == "response.created"
    assert events[0]["response"]["model"] == ALIAS and events[-1]["response"]["model"] == ALIAS
    assert "All tests " in answered.text

    fake.model = "some-other-model"
    refused = await client.post(ROUTE, json=_body(), headers=headers)
    assert refused.status_code == 502
    assert refused.headers["x-octryx-gateway-reason"] == "served_model_not_admitted"


async def test_namespace_tools_reach_the_upstream_flat_and_the_call_comes_back_namespaced(client, responses_setup):  # noqa: F811
    """Codex's MCP tools (a ``namespace``) are plain function tools upstream; the answer's call has its namespace."""
    fake, build = responses_setup
    namespace = "mcp__octryx_knowledge"
    flat = f"{namespace}__workflow_catalog"
    call = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": flat, "arguments": "{}",
            "status": "completed"}

    def handle(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        stream = "".join([
            _sse({"type": "response.created", "response": _response(MODEL_GROUP)}),
            _sse({"type": "response.output_item.added", "output_index": 0, "item": {**call, "arguments": ""}}),
            _sse({"type": "response.output_item.done", "output_index": 0, "item": call}),
            _sse({"type": "response.completed", "response": _response(MODEL_GROUP, "completed", usage=USAGE,
                                                                       output=[call])}),
        ]).encode("utf-8")
        return httpx.Response(200, content=stream, headers={"content-type": "text/event-stream"})

    fake.handle = handle
    body = _body()
    body["tools"] = [{"type": "namespace", "name": namespace, "description": "", "tools": [
        {"type": "function", "name": "workflow_catalog", "description": "List workflows.",
         "parameters": {"type": "object", "properties": {}}}]}]
    answered = await client.post(ROUTE, json=body, headers=await build())

    assert answered.status_code == 200, answered.text
    sent = json.loads(fake.requests[-1].content)
    assert [tool["name"] for tool in sent["tools"]] == [flat] and sent["tools"][0]["type"] == "function"
    events = [json.loads(line[6:]) for line in answered.text.splitlines() if line.startswith("data: ")]
    items = [event["item"] for event in events if "item" in event]
    assert all(item["namespace"] == namespace and item["name"] == "workflow_catalog" for item in items)
    completed = next(event for event in events if event["type"] == "response.completed")
    assert completed["response"]["output"][0]["namespace"] == namespace


async def test_the_alias_answer_budget_is_asked_for_when_the_client_sends_none(client, responses_setup, monkeypatch):  # noqa: F811
    """Codex sends no ``max_output_tokens``; an alias that declares one gets it upstream (never over the client's)."""
    from dataclasses import replace

    from app.services.model_gateway.inbound import service as service_module

    fake, build = responses_setup
    original = service_module.admit_inbound_call

    async def with_budget(*args, **kwargs):
        admitted = await original(*args, **kwargs)
        return replace(admitted, entry=replace(admitted.entry, max_output_tokens=8192))

    monkeypatch.setattr(service_module, "admit_inbound_call", with_budget)
    headers = await build()
    assert (await client.post(ROUTE, json=_body(), headers=headers)).status_code == 200
    assert json.loads(fake.requests[-1].content)["max_output_tokens"] == 8192
    own = {**_body(), "max_output_tokens": 100}
    assert (await client.post(ROUTE, json=own, headers=headers)).status_code == 200
    assert json.loads(fake.requests[-1].content)["max_output_tokens"] == 100


def test_an_alias_answer_budget_must_be_a_positive_int_within_the_context():
    from app.services.model_gateway.litellm.alias_catalog import resolve_alias_admission

    def admitted(value):
        entry = {"model_group": "g", "context_limit": 32000, "data_policy_class": "internal",
                 "capabilities": {"tools": True}, "cost": {"source": "governed_free", "contract_reference": "x"}}
        if value is not None:
            entry["max_output_tokens"] = value
        return resolve_alias_admission("a", {"litellm_gateway": {"aliases": {"a": entry}}})

    assert admitted(None).entry.max_output_tokens is None
    assert admitted(8192).entry.max_output_tokens == 8192
    for bad in (0, -1, 64000, "8192", True, 1.5):
        assert admitted(bad).denial_reason == "alias_max_output_tokens_invalid", bad


async def test_a_local_model_gets_at_least_8k_to_answer(client, responses_setup, monkeypatch):  # noqa: F811
    """A local reasoning model stops mid-thought below about 8k output tokens."""
    from app.services.model_gateway.inbound import openai_service

    fake, build = responses_setup
    monkeypatch.setattr(openai_service, "local_upstream", lambda base_url: True)
    headers = await build()
    assert (await client.post(ROUTE, json={**_body(), "max_output_tokens": 100}, headers=headers)).status_code == 200
    assert json.loads(fake.requests[-1].content)["max_output_tokens"] == 8192
    assert (await client.post(ROUTE, json={**_body(), "max_output_tokens": 20000}, headers=headers)).status_code == 200
    assert json.loads(fake.requests[-1].content)["max_output_tokens"] == 20000
