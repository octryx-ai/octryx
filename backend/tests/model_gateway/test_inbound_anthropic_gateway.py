"""Contract tests for the inbound Anthropic Messages gateway (octryx-claude PoC)."""

# ruff: noqa: F811  (the shared ``gateway_setup`` fixture is imported, then requested by name)
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.models import Message, ToolCall, TurnTrace, UsageEvent
from app.services.oauth_provider.tokens import DEFAULT_RESOURCE_AUDIENCE

from .conftest import ALIAS, MODEL_GROUP, VIRTUAL_KEY
from .inbound_gateway_support import gateway_setup  # noqa: F401 - fixture

ROUTE = "/api/v1/model-gateway/anthropic/v1/messages"
AWS_KEY_LOOKALIKE = "AKIA" + "ABCDEFGHIJKLMNOP"


def _request_body(*, newest_text: str = "Now summarize.") -> dict[str, Any]:
    return {
        "model": ALIAS,
        "max_tokens": 1024,
        "stream": True,
        "system": [{"type": "text", "text": "You are a coding agent."}],
        "tools": [{"name": "Bash", "description": "Run a command", "input_schema": {"type": "object"}}],
        "messages": [
            {"role": "user", "content": "Run the tests."},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Running them."},
                    {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest -q"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "3 passed"},
                    {"type": "text", "text": "<system-reminder>internal note</system-reminder>"},
                    {"type": "text", "text": newest_text},
                ],
            },
        ],
    }


async def test_streamed_call_is_relayed_under_the_alias_and_recorded(client, db, gateway_setup):
    fake, build = gateway_setup
    headers = await build()

    response = await client.post(ROUTE, json=_request_body(), headers=headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["request-id"] == "req_upstream_1"
    assert f'"model":"{ALIAS}"' in response.text
    assert MODEL_GROUP not in response.text
    assert "event: ping" in response.text and "All tests pass." in response.text

    [sent] = fake.requests
    assert sent.url.path == "/v1/messages"
    assert json.loads(sent.content)["model"] == MODEL_GROUP
    assert sent.headers["authorization"] == f"Bearer {VIRTUAL_KEY}"
    assert sent.headers["anthropic-beta"] == "interleaved-thinking-2025-05-14"
    assert "x-api-key" not in sent.headers and "x-octryx-session" not in sent.headers

    [usage] = (await db.execute(select(UsageEvent).where(UsageEvent.model == ALIAS))).scalars().all()
    assert (usage.tokens_in, usage.tokens_out, usage.cache_read_tokens) == (1000, 500, 200)
    # Catalog pricing over all prompt tokens: (1200 * 1.0 + 500 * 2.0) / 1e6.
    assert Decimal(str(usage.cost)) == Decimal("0.002200")
    assert (usage.cost_source, usage.cost_status, usage.request_id) == (
        "catalog_pricing", "catalog_pricing", "req_upstream_1"
    )

    [call] = (await db.execute(select(ToolCall).where(ToolCall.session_id == usage.session_id))).scalars().all()
    assert (call.request_id, call.tool_name, call.status) == ("toolu_1", "Bash", "success")
    assert call.parameters["source"] == "model_gateway" and call.parameters["command"] == "pytest -q"
    assert call.result == {"is_error": False, "excerpt": "3 passed"}

    messages = (await db.execute(select(Message).where(Message.session_id == usage.session_id))).scalars().all()
    assert sorted((item.role, item.content) for item in messages) == [
        ("assistant", "All tests pass."),
        ("user", "Now summarize."),
    ]
    [trace] = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == usage.session_id))).scalars().all()
    assert trace.usage_json["stream_completed"] is True and trace.usage_json["stop_reason"] == "end_turn"
    assert trace.context_snapshot_json["claude_session_id"] == "c0ffee00-1111-2222-3333-444455556666"

    # A client retry of the same request does not duplicate the tool call or the prompt.
    retry = await client.post(ROUTE, json=_request_body(), headers=headers)
    assert retry.status_code == 200
    calls = (await db.execute(select(ToolCall).where(ToolCall.session_id == usage.session_id))).scalars().all()
    prompts = (
        await db.execute(select(Message).where(Message.session_id == usage.session_id, Message.role == "user"))
    ).scalars().all()
    assert len(calls) == 1 and len(prompts) == 1


async def test_a_secret_in_the_newest_turn_is_refused_before_dispatch(client, db, gateway_setup):
    from tests.content_security.gateway_route_support import configure

    fake, build = gateway_setup
    headers = await build()
    await configure(db, headers["X-Octryx-Workspace"], "secrets", "refuse")  # the default masks
    # Only this request's traces: rows another test committed on the same xdist worker are not ours.
    traces_before = len((await db.execute(select(TurnTrace.id))).all())

    response = await client.post(ROUTE, json=_request_body(newest_text=f"use {AWS_KEY_LOOKALIKE}"), headers=headers)

    assert response.status_code == 400
    assert response.headers["x-octryx-gateway-state"] == "denied"
    assert response.headers["x-octryx-gateway-reason"] == "secret_detected_in_prompt"
    error = response.json()["error"]
    assert error["type"] == "invalid_request_error"
    assert AWS_KEY_LOOKALIKE not in response.text
    assert fake.requests == []
    assert len((await db.execute(select(TurnTrace.id))).all()) == traces_before
    assert (await db.execute(select(ToolCall).where(ToolCall.request_id == "toolu_1"))).scalars().all() == []


async def test_an_alias_the_workspace_has_not_granted_is_denied_before_dispatch(client, gateway_setup):
    fake, build = gateway_setup
    headers = await build(allowed_aliases=("some-other-alias",))

    response = await client.post(ROUTE, json=_request_body(), headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "permission_error"
    assert response.headers["x-octryx-gateway-state"] == "denied"
    assert fake.requests == []


async def test_a_token_minted_for_another_audience_is_unauthorized(client, gateway_setup):
    fake, build = gateway_setup
    headers = await build(audience=DEFAULT_RESOURCE_AUDIENCE)

    response = await client.post(ROUTE, json=_request_body(), headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert response.headers["x-octryx-gateway-reason"] == "gateway_token_invalid"
    assert fake.requests == []


async def test_count_tokens_without_upstream_support_is_an_explicit_404(client, gateway_setup):
    fake, build = gateway_setup
    headers = await build()

    response = await client.post(f"{ROUTE}/count_tokens", json=_request_body(), headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["type"] == "not_found_error"
    assert response.headers["x-octryx-gateway-reason"] == "count_tokens_not_supported"
    assert "must not leak" not in response.text
    [sent] = fake.requests
    assert sent.url.path == "/v1/messages/count_tokens"
