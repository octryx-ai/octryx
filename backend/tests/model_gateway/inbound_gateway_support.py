"""The governed inbound Anthropic Messages route with LiteLLM as an ``httpx.MockTransport`` that records every
request."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.models import OAuthGrant, Project, User, UserProject
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.model_gateway.inbound import upstream as inbound_upstream
from app.services.oauth_provider.tokens import mint_access_token
from app.services.secret import set_secret_value
from tests.model_gateway.conftest import (
    ALIAS,
    GATEWAY_HOST,
    MODEL_GROUP,
    VIRTUAL_KEY,
    gateway_provider,
    granted_project_config,
)

SESSION_KEY = str(uuid.uuid4())


def _sse(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


STREAM = "".join(
    [
        _sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": MODEL_GROUP,
                    "content": [],
                    "usage": {"input_tokens": 1000, "output_tokens": 1, "cache_read_input_tokens": 200},
                },
            },
        ),
        _sse("ping", {"type": "ping"}),
        _sse("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "text", "text": ""}}),
        _sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta", "text": "All tests pass."}}),
        _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                               "usage": {"output_tokens": 500}}),
        _sse("message_stop", {"type": "message_stop"}),
    ]
)


class FakeAnthropicGateway:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/count_tokens"):
            return httpx.Response(404, json={"error": {"message": "upstream detail that must not leak"}})
        return httpx.Response(
            200,
            content=STREAM.encode("utf-8"),
            headers={"content-type": "text/event-stream", "request-id": "req_upstream_1"},
        )


@pytest.fixture
async def gateway_setup(db, monkeypatch):
    fake = FakeAnthropicGateway()
    monkeypatch.setattr(inbound_upstream, "upstream_transport", lambda: httpx.MockTransport(fake.handle))
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    async def build(*, allowed_aliases: tuple[str, ...] = (ALIAS,), audience: str = GATEWAY_AUDIENCE):
        project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}",
                          config=granted_project_config(*allowed_aliases), is_active=True)
        db.add(project)
        db.add(UserProject(user_id=user.id, project_id=project.id, role="member"))
        secret = await set_secret_value(db, tool_name="litellm_gateway", field_name="virtual_key",
                                        project_id=None, value=VIRTUAL_KEY)
        # A bare-origin endpoint (``http://127.0.0.1:4000``): the
        # route must address ``/v1/messages`` itself.
        db.add(gateway_provider(name=f"litellm-{uuid.uuid4().hex[:6]}", api_key_secret_ref=secret.id,
                                endpoint_url=f"https://{GATEWAY_HOST}"))
        grant = OAuthGrant(id=str(uuid.uuid4()), user_id=user.id, client_id="octryx-claude-test",
                           scopes=[SCOPE_MODEL_INVOKE])
        db.add(grant)
        await db.commit()
        token, _ = mint_access_token(user_id=user.id, client_id=grant.client_id, grant_id=grant.id,
                                     scopes=[SCOPE_MODEL_INVOKE], resource=audience)
        return {
            "Authorization": f"Bearer {token}",
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
            "X-Octryx-Session": SESSION_KEY,
            "X-Octryx-Workspace": project.id,
            "x-claude-code-session-id": "c0ffee00-1111-2222-3333-444455556666",
        }

    return fake, build
