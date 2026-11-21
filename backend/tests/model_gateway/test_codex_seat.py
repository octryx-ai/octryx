"""The Codex seat route: Codex on the person's own ChatGPT login through the platform (variant A).

ChatGPT's Codex backend is an ``httpx.MockTransport`` that records every request, so a refusal is proven to send
nothing upstream and the forwarded header set and path are checked exactly. No live ChatGPT call is made.
"""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.models import AgentPresence, Message, ToolCall, TurnTrace, UsageEvent
from tests.model_gateway.codex_seat_support import (  # noqa: F401
    ACCOUNT,
    CHATGPT_TOKEN,
    CODEX_SESSION,
    MODEL,
    ROUTE,
    STREAM,
    UPSTREAM_HEADERS,
    USAGE,
    _body,
    _codex_session,
    _headers,
    chatgpt,
)

# --- the happy path ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_codex_seat_call_is_forwarded_with_only_allowed_headers_and_relayed_unchanged(client, db, chatgpt):  # noqa: F811
    workspace_id, user_id, gateway, credential = await _codex_session(client, db)

    response = await client.post(ROUTE, json=_body(), headers=_headers(gateway, credential))

    assert response.status_code == 200, response.text
    assert response.text == STREAM  # byte for byte: no model rewrite on the seat
    assert response.headers["x-codex-primary-used-percent"] == "12.5"
    assert response.headers["x-codex-turn-state"] == "sticky-1"
    assert "set-cookie" not in response.headers and "x-upstream-internal" not in response.headers
    [sent] = chatgpt.requests
    assert (sent.url.scheme, sent.url.host, sent.url.path) == ("https", "chatgpt.com", "/backend-api/codex/responses")
    transport = {"host", "content-length", "accept-encoding", "connection"}
    assert set(sent.headers) - transport == {
        "authorization", "chatgpt-account-id", "openai-beta", "originator", "session_id", "session-id", "version",
        "accept", "content-type", "user-agent"}  # user-agent: the test client's own
    assert sent.headers["authorization"] == f"Bearer {CHATGPT_TOKEN}"
    assert sent.headers["chatgpt-account-id"] == ACCOUNT
    assert json.loads(sent.content) == _body()  # unchanged, namespace tools not flattened

    [usage] = (await db.execute(select(UsageEvent).where(UsageEvent.user_id == user_id))).scalars().all()
    assert (usage.provider, usage.model, float(usage.cost), usage.cost_source) == (
        "openai_codex_seat", MODEL, 0.0, "seat_subscription")
    assert (usage.tokens_in, usage.tokens_out, usage.cache_read_tokens, usage.request_id) == (
        1000, 500, 200, "req_codex_1")
    [call] = (await db.execute(select(ToolCall).where(ToolCall.session_id == usage.session_id))).scalars().all()
    assert (call.request_id, call.tool_name, call.status) == ("call_1", "Bash", "success")  # Codex shell calls are recorded as Bash
    assert call.parameters["block_index"] == 0  # read evidence reads these rows
    messages = (await db.execute(select(Message).where(Message.session_id == usage.session_id))).scalars().all()
    # The answer called a tool, so it is not a final assistant message yet (as on every route).
    assert [(item.role, item.content) for item in messages] == [("user", "Now summarize.")]
    [trace] = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == usage.session_id))).scalars().all()
    assert (trace.provider, trace.usage_json["stop_reason"], trace.usage_json["stream_completed"]) == (
        "openai_codex_seat", "tool_use", True)
    assert trace.context_snapshot_json["codex_session_id"] == CODEX_SESSION
    row = (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).scalar_one()
    await db.refresh(row)
    assert (row.profile, row.model) == ("seat", MODEL)


@pytest.mark.asyncio
async def test_chatgpt_rate_limit_windows_land_in_the_presence_allowance_kept_apart_from_the_claude_seat(
        client, db, chatgpt):  # noqa: F811
    # ChatGPT's primary (5 h) and secondary (7 d) windows go into the same presence fields as the Claude
    # seat's; only the numbers, and the usage read keeps the two seats apart.
    from app.services.agent_gateway.usage_read import own_gateway_usage

    workspace_id, user_id, gateway, credential = await _codex_session(client, db)
    UPSTREAM_HEADERS.update({"x-codex-primary-reset-at": "1900000000", "x-codex-secondary-used-percent": "81",
                             "x-codex-secondary-reset-after-seconds": "3600", "x-codex-primary-window-minutes": "300"})
    try:
        response = await client.post(ROUTE, json=_body(), headers=_headers(gateway, credential))
    finally:
        for name in ("x-codex-primary-reset-at", "x-codex-secondary-used-percent",
                     "x-codex-secondary-reset-after-seconds", "x-codex-primary-window-minutes"):
            UPSTREAM_HEADERS.pop(name)

    assert response.status_code == 200, response.text
    row = (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).scalar_one()
    await db.refresh(row)
    assert (row.five_hour_pct, row.seven_day_pct, row.allowance_status, row.state) == (12.5, 81.0, None, "active")
    assert row.five_hour_resets_at.isoformat() == "2030-03-17T17:46:40"
    assert row.seven_day_resets_at is not None and row.allowance_updated_at is not None
    usage = await own_gateway_usage(db, user_id=user_id, workspace_id=workspace_id)
    assert usage["seat_allowance"] is None, "a Codex window is not the Claude subscription's"
    codex = usage["codex_seat_allowance"]
    assert (codex["five_hour_pct"], codex["seven_day_pct"], codex["five_hour_resets_at"]) == (
        12.5, 81.0, "2030-03-17T17:46:40Z")


def test_the_codex_windows_are_parsed_from_numbers_only():
    from datetime import datetime

    from app.services.agent_gateway.allowance import parse_codex_allowance

    now = datetime(2026, 11, 15, 12, 0)
    parsed = parse_codex_allowance({"X-Codex-Primary-Used-Percent": "100", "x-codex-primary-reset-after-seconds": "60",
                                    "x-codex-secondary-used-percent": "nan", "x-codex-secondary-reset-at": "12",
                                    "x-codex-rate-limit-reached-type": "rate_limit_reached",
                                    "authorization": "Bearer never-read"}, now=now)
    assert (parsed.five_hour_pct, parsed.five_hour_resets_at, parsed.seven_day_pct, parsed.seven_day_resets_at) == (
        100.0, datetime(2026, 11, 15, 12, 1), None, None)
    assert parsed.status == "rejected" and parsed.limit_reached
    for junk in ({"x-codex-primary-used-percent": "-1"}, {"x-codex-primary-used-percent": "1e9"},
                 {"x-codex-rate-limit-reached-type": "anything"}, {"x-codex-primary-reset-after-seconds": "-5"},
                 {"anthropic-ratelimit-unified-5h-utilization": "0.5"}):
        assert not parse_codex_allowance(junk, now=now).observed, junk


@pytest.mark.asyncio
async def test_a_non_streamed_answer_is_relayed_and_recorded(client, db, chatgpt):  # noqa: F811
    _workspace_id, user_id, gateway, credential = await _codex_session(client, db)
    answer = {"id": "resp_2", "model": MODEL, "status": "completed", "usage": USAGE, "output": [
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]}]}
    chatgpt.handle = lambda request: (chatgpt.requests.append(request), httpx.Response(200, json=answer))[1]

    response = await client.post(ROUTE, json=_body(stream=False), headers=_headers(gateway, credential))

    assert response.status_code == 200 and response.json() == answer
    [usage] = (await db.execute(select(UsageEvent).where(UsageEvent.user_id == user_id))).scalars().all()
    assert (usage.tokens_in, usage.tokens_out) == (1000, 500)
    messages = (await db.execute(select(Message).where(Message.session_id == usage.session_id))).scalars().all()
    assert sorted((item.role, item.content) for item in messages) == [
        ("assistant", "Done."), ("user", "Now summarize.")]


@pytest.mark.asyncio
async def test_upstream_errors_are_relayed_unchanged(client, db, chatgpt):  # noqa: F811
    _workspace_id, _user, gateway, credential = await _codex_session(client, db)
    chatgpt.status = 429

    response = await client.post(ROUTE, json=_body(), headers=_headers(gateway, credential))

    assert response.status_code == 429 and response.json()["error"]["type"] == "usage_limit_reached"
    assert response.headers["retry-after"] == "60"
