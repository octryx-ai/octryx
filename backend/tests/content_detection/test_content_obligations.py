"""Custom-policy obligations at the gateway of external coding agents: never applied there (owner decision).

A deciding policy that asks to mask or reroute refuses the request (``content_handling_gateway_refused``) on the seat
and on the governed route: nothing is masked, nothing is routed, nothing reaches any upstream. A plain block keeps
``content_policy_denied``; shadow sends unchanged.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.models import ContentConversationState, PolicyDecisionLog
from app.services.model_gateway.inbound import upstream as inbound_upstream
from app.services.policy_engine.decision_log import flush_decision_log
from tests.agent_gateway.seat_presence_support import (
    SEAT,
    _found_anywhere,
    _seat_headers,
    _seat_session,
)
from tests.content_detection.content_obligations_support import (
    EMAIL,
    ROUTE_GOVERNED,
    ROUTED,
    ROUTED_ID,
    _governed_alias,
)
from tests.model_gateway.inbound_gateway_support import STREAM
from tests.model_gateway.test_inbound_anthropic_gateway import _request_body
from tests.policy_engine_support import use_custom_policies

HOOK_EXECUTED = "/api/v1/agent-gateway/sessions/tool-executed"
#: The gateway examines credentials and credential assignments only (C12F-08): its policy tests name an assignment.
ASSIGNMENT = "password=Hunter2024x"
GATEWAY_TEXT = f"login {ASSIGNMENT} declined"
GATEWAY_ROUTED = ROUTED.replace('containsAny(["email", "phone"])', 'contains("credential_assignment")')



class FakeLiteLLM:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, content=STREAM.encode(), headers={"content-type": "text/event-stream",
                                                                      "request-id": "req_gov_1"})

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(item.content) for item in self.requests]


@pytest.fixture
def litellm(monkeypatch) -> FakeLiteLLM:
    fake = FakeLiteLLM()
    monkeypatch.setattr(inbound_upstream, "upstream_transport", lambda: httpx.MockTransport(fake.handle))
    return fake


def _seat_body(*texts: str) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        if index:
            messages.append({"role": "assistant", "content": "ok"})
        messages.append({"role": "user", "content": text})
    return {"model": "claude-sonnet-5", "max_tokens": 64, "stream": True, "messages": messages,
            "tools": [{"name": "Bash", "description": "Run", "input_schema": {"type": "object"}}]}


async def _records(db) -> list[PolicyDecisionLog]:
    await flush_decision_log(db)
    await db.commit()
    return list((await db.execute(select(PolicyDecisionLog))).scalars())


async def _seat(client, db, *, approved=("pii",), grant=True):
    workspace_id, _user, gateway, credential = await _seat_session(client, db)
    await _governed_alias(db, workspace_id, approved=list(approved), grant=grant)
    return workspace_id, gateway, credential


@pytest.mark.committed_db  # the seat call records in its own session (see test_seat_presence)
@pytest.mark.asyncio
async def test_a_seat_request_a_routing_policy_denies_is_refused_never_routed(client, db, anthropic, litellm):
    _workspace, gateway, credential = await _seat(client, db)
    use_custom_policies(GATEWAY_ROUTED, mode="enforce")
    response = await client.post(SEAT, json=_seat_body(GATEWAY_TEXT), headers=_seat_headers(gateway, credential))
    assert response.status_code == 403
    assert response.headers["x-octryx-gateway-reason"] == "content_handling_gateway_refused"
    message = response.json()["error"]["message"]
    assert ROUTED_ID in message and "Hunter2024x" not in message
    assert anthropic.requests == [] and litellm.requests == [], "never the seat, never the governed alias"
    assert [row for row in await _records(db) if row.outcome in ("remedied", "would_remedy")] == []
    assert (await db.execute(select(ContentConversationState))).scalars().all() == []


@pytest.mark.committed_db  # the seat call records in its own session (see test_seat_presence)
@pytest.mark.asyncio
async def test_shadow_sends_unchanged(client, db, anthropic, litellm):
    _workspace, gateway, credential = await _seat(client, db)
    use_custom_policies(ROUTED, mode="shadow")
    response = await client.post(SEAT, json=_seat_body(f"mail {EMAIL}"), headers=_seat_headers(gateway, credential))
    assert response.status_code == 200 and len(anthropic.requests) == 1 and litellm.requests == []
    assert EMAIL in anthropic.requests[0].content.decode()
    assert [row for row in await _records(db) if row.outcome == "would_remedy"] == []


@pytest.mark.asyncio
async def test_a_governed_mask_obligation_refuses_and_a_plain_block_keeps_its_reason(client, db, gateway_setup):
    fake, build = gateway_setup
    headers = await build()
    use_custom_policies(GATEWAY_ROUTED, mode="enforce")
    masked = await client.post(ROUTE_GOVERNED, json=_request_body(newest_text=GATEWAY_TEXT), headers=headers)
    assert masked.headers["x-octryx-gateway-reason"] == "content_handling_gateway_refused"
    block = ('@id("no-mail")\nforbid (principal, action == Action::"call_model", resource)\n'
             'when { context.content.detected.contains("credential_assignment") };')
    use_custom_policies(GATEWAY_ROUTED + "\n" + block, mode="enforce")
    plain = await client.post(ROUTE_GOVERNED, json=_request_body(newest_text=GATEWAY_TEXT), headers=headers)
    assert plain.headers["x-octryx-gateway-reason"] == "content_policy_denied"
    assert "no-mail" in plain.json()["error"]["message"]
    assert fake.requests == []
    assert await _found_anywhere(db, "Hunter2024x") == []
