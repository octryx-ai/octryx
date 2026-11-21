"""A seat session's model picker: it lists its subscription models and, with the opt-in, company models, and a chosen company model runs the governed path with its refusals, token counts, secret scan and budgets."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.models import Project, TurnTrace, UsageEvent
from app.services.agent_gateway.seat_policy_keys import BASELINE_SEAT_MODELS
from app.services.model_gateway.inbound import governed_dispatch as inbound_service
from app.services.model_gateway.inbound import seat_upstream
from app.services.model_gateway.inbound import upstream as inbound_upstream
from app.services.policy_engine.shadow import decision_counters
from tests.model_gateway.inbound_model_picker_support import (
    MODELS,
    NO_TOOLS,
    OPT_IN,
    SECOND,
    UNGRANTED,
    _ids,
    _workspace,
)
from tests.policy_engine_support import use_custom_policies

from .conftest import ALIAS, MODEL_GROUP, VIRTUAL_KEY

SEAT_MODELS = "/api/v1/model-gateway/anthropic/seat/v1/models"


SEAT_MESSAGES = "/api/v1/model-gateway/anthropic/seat/v1/messages"


SEAT_COUNT = "/api/v1/model-gateway/anthropic/seat/v1/messages/count_tokens"


REGISTER = "/api/v1/agent-gateway/sessions/register"


SUBSCRIPTION = "sk-ant-oat01-" + "s" * 60


def _sse(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


STREAM = "".join([
    _sse("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": MODEL_GROUP, "content": [],
        "usage": {"input_tokens": 1000, "output_tokens": 1}}}),
    _sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}),
    _sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "Done."}}),
    _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
    _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                           "usage": {"output_tokens": 500}}),
    _sse("message_stop", {"type": "message_stop"}),
])


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/count_tokens"):
            return httpx.Response(200, json={"input_tokens": 42})
        return httpx.Response(200, content=STREAM.encode(), headers={"content-type": "text/event-stream",
                                                                     "request-id": "req_company_1"})


@pytest.fixture
def upstreams(monkeypatch) -> tuple[Recorder, Recorder]:
    litellm, anthropic = Recorder(), Recorder()
    monkeypatch.setattr(inbound_upstream, "upstream_transport", lambda: httpx.MockTransport(litellm.handle))
    monkeypatch.setattr(seat_upstream, "seat_transport", lambda: httpx.MockTransport(anthropic.handle))
    return litellm, anthropic


async def _seat(client, gateway: dict[str, str]) -> dict[str, str]:
    registered = await client.post(REGISTER, json={"profile": "seat", "client": "octryx-claude",
                                                   "client_version": "0.3.0"}, headers=gateway)
    assert registered.status_code == 200, registered.text
    return {
        "authorization": f"Bearer {SUBSCRIPTION}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": ("oauth-2025-04-20,inte" + "rleaved-thinking-2025-05-14"),
        "x-claude-code-session-id": "c0ffee00-1111-2222-3333-444455556666",
        "x-octryx-session": gateway["x-octryx-session"],
        "x-octryx-workspace": gateway["x-octryx-workspace"],
        "x-octryx-seat-credential": registered.json()["seat_credential"],
    }


def _body(model: str, text: str = "Fix the test.") -> dict[str, Any]:
    return {"model": model, "max_tokens": 64, "stream": True,
            "tools": [{"name": "Bash", "description": "Run", "input_schema": {"type": "object"}}],
            "messages": [{"role": "user", "content": text}]}


# --- seat route ------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_seat_session_lists_only_its_subscription_models_by_default(client, db, upstreams):
    _workspace_id, gateway = await _workspace(db, policy={"seat_mode": "allowed"})
    seat = await _seat(client, gateway)

    payload = (await client.get(SEAT_MODELS, params={"limit": 1000}, headers=seat)).json()

    assert _ids(payload) == [*BASELINE_SEAT_MODELS]
    assert {row["source"] for row in payload["data"]} == {"subscription"}
    assert upstreams[0].requests == upstreams[1].requests == []


@pytest.mark.asyncio
async def test_with_the_opt_in_a_seat_session_also_lists_company_models_under_their_explicit_id(client, db):
    _workspace_id, gateway = await _workspace(db, policy=OPT_IN)
    seat = await _seat(client, gateway)

    payload = (await client.get(SEAT_MODELS, params={"limit": 1000}, headers=seat)).json()

    assert _ids(payload) == [*BASELINE_SEAT_MODELS, f"company/{ALIAS}", f"company/{SECOND}"]
    company = payload["data"][len(BASELINE_SEAT_MODELS)]
    assert (company["display_name"], company["source"]) == ("General model (company)", "company")
    assert "billed to the Workspace budget" in company["description"]


@pytest.mark.asyncio
async def test_the_seat_list_is_refused_like_a_seat_call(client, db):
    _workspace_id, gateway = await _workspace(db, policy={"seat_mode": "allowed"})
    seat = await _seat(client, gateway)
    project = await db.get(Project, gateway["x-octryx-workspace"])
    project.config = {**project.config, "agent_gateway_policy": {"seat_mode": "forbidden"}}
    await db.commit()

    refused = await client.get(SEAT_MODELS, headers=seat)

    assert refused.status_code == 403 and "seat_mode_forbidden" in refused.json()["error"]["message"]
    assert (await client.get(SEAT_MODELS, headers={**seat, "x-octryx-seat-credential": "x" * 43})
            ).status_code == 401


@pytest.mark.asyncio
async def test_a_company_model_in_a_seat_session_is_refused_without_the_opt_in(client, db, upstreams):
    _workspace_id, gateway = await _workspace(db, policy={"seat_mode": "allowed"})
    seat = await _seat(client, gateway)

    refused = await client.post(SEAT_MESSAGES, json=_body(f"company/{ALIAS}"), headers=seat)

    assert refused.status_code == 403
    message = refused.json()["error"]["message"]
    assert "seat_governed_models_not_allowed" in message and "--profile governed" in message
    assert upstreams[0].requests == upstreams[1].requests == []


@pytest.mark.asyncio
async def test_a_company_model_in_a_seat_session_runs_the_governed_path(client, db, upstreams):
    litellm, anthropic = upstreams
    _workspace_id, gateway = await _workspace(db, policy=OPT_IN)
    seat = await _seat(client, gateway)

    response = await client.post(SEAT_MESSAGES, json=_body(f"company/{ALIAS}"), headers=seat)

    assert response.status_code == 200, response.text
    assert "Done." in response.text and anthropic.requests == []
    [sent] = litellm.requests
    assert json.loads(sent.content)["model"] == MODEL_GROUP
    assert sent.headers["authorization"] == f"Bearer {VIRTUAL_KEY}"
    assert sent.headers["anthropic-beta"] == ("inte" + "rleaved-thinking-2025-05-14")
    assert SUBSCRIPTION not in str(sent.headers) and "x-octryx-seat-credential" not in sent.headers
    [usage] = (await db.execute(select(UsageEvent).where(UsageEvent.model == ALIAS))).scalars().all()
    assert (usage.model, usage.cost_source, usage.tokens_in, usage.tokens_out) == (ALIAS, "catalog_pricing", 1000, 500)
    [trace] = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == usage.session_id))).scalars().all()
    evidence = trace.usage_json["gateway_evidence"]
    assert (evidence["client_profile"], evidence["dispatch_owner"]) == ("seat", "model_gateway_inbound_anthropic")
    assert trace.context_snapshot_json["claude_session_id"] == "c0ffee00-1111-2222-3333-444455556666"
    assert set(sent.headers) & {"x-claude-code-session-id", "x-api-key", "cookie"} == set()
    counters = decision_counters()["model_admission"]
    assert counters["match"] >= 1 and counters["mismatch"] == counters["error"] == 0


@pytest.mark.asyncio
async def test_the_seat_company_path_counts_tokens_through_the_company_gateway(client, db, upstreams):
    litellm, anthropic = upstreams
    _workspace_id, gateway = await _workspace(db, policy=OPT_IN)
    seat = await _seat(client, gateway)

    counted = await client.post(SEAT_COUNT, json=_body(f"company/{ALIAS}"), headers=seat)

    assert counted.status_code == 200 and counted.json() == {"input_tokens": 42}
    assert [request.url.path for request in litellm.requests] == ["/v1/messages/count_tokens"]
    assert anthropic.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("model", "status", "reason"), [
    (f"company/{UNGRANTED}", 403, "model_alias_not_granted_for_project"),
    (f"company/{NO_TOOLS}", 403, "capability_not_declared"),
    ("company/", 400, "request_body_invalid"),
    ("company/octryx-unknown", 403, "alias_not_listed"),
])
async def test_a_company_model_the_workspace_does_not_admit_is_refused_with_a_clear_message(
    client, db, upstreams, model, status, reason
):
    _workspace_id, gateway = await _workspace(db, policy=OPT_IN)
    seat = await _seat(client, gateway)

    refused = await client.post(SEAT_MESSAGES, json=_body(model), headers=seat)

    assert refused.status_code == status, refused.text
    assert reason in refused.json()["error"]["message"]
    if model == f"company/{UNGRANTED}":
        assert "Run /model to see the models it offers." in refused.json()["error"]["message"]
    assert upstreams[0].requests == upstreams[1].requests == []


@pytest.mark.asyncio
async def test_the_seat_company_path_keeps_the_secret_scan_and_the_budgets(client, db, upstreams, monkeypatch):
    _workspace_id, gateway = await _workspace(db, policy=OPT_IN)
    seat = await _seat(client, gateway)

    secret = await client.post(SEAT_MESSAGES, json=_body(f"company/{ALIAS}", "key AKIA" + "ABCDEFGHIJKLMNOP"),
                               headers=seat)
    assert secret.status_code == 400 and "secret_detected_in_prompt" in secret.json()["error"]["message"]

    class Exhausted:
        allowed, state, reason = False, "denied", "gateway_daily_budget_exhausted"

        def hint(self) -> str:
            return "Daily budget reached."

    async def exhausted(*_args, **_kwargs):
        return Exhausted()

    monkeypatch.setattr(inbound_service, "check_daily_budget", exhausted)
    budget = await client.post(SEAT_MESSAGES, json=_body(f"company/{ALIAS}"), headers=seat)
    assert budget.status_code == 403 and "gateway_daily_budget_exhausted" in budget.json()["error"]["message"]
    assert upstreams[0].requests == upstreams[1].requests == []


@pytest.mark.asyncio
async def test_a_subscription_model_is_never_sent_to_the_company_gateway(client, db, upstreams):
    litellm, anthropic = upstreams
    _workspace_id, gateway = await _workspace(db, policy=OPT_IN)
    seat = await _seat(client, gateway)

    alias = await client.post(SEAT_MESSAGES, json=_body(ALIAS), headers=seat)
    plain = await client.post(SEAT_MESSAGES, json=_body("claude-sonnet-5"), headers=seat)

    assert plain.status_code == 200 and litellm.requests == [] and len(anthropic.requests) == 1
    assert alias.status_code == 400 and "seat_model_not_allowed" in alias.json()["error"]["message"]
    assert "Run /model" in alias.json()["error"]["message"]


@pytest.mark.asyncio
async def test_cedar_call_model_sees_the_seat_profile_and_the_chosen_alias(client, db, upstreams):
    _workspace_id, gateway = await _workspace(db, policy=OPT_IN)
    seat = await _seat(client, gateway)
    use_custom_policies(f'@id("no-seat-general")\nforbid (principal is AgentSession, action == Action::"call_model", '
                        f'resource == ModelAlias::"{ALIAS}") when {{ principal.profile == "seat" }};', mode="enforce")

    listed = (await client.get(SEAT_MODELS, params={"limit": 1000}, headers=seat)).json()
    refused = await client.post(SEAT_MESSAGES, json=_body(f"company/{ALIAS}"), headers=seat)
    governed = (await client.get(MODELS, params={"limit": 1000}, headers=gateway)).json()

    assert f"company/{ALIAS}" not in _ids(listed) and f"company/{SECOND}" in _ids(listed)
    assert refused.status_code == 403 and "cedar_policy_denied" in refused.json()["error"]["message"]
    assert ALIAS in _ids(governed)  # the same user's governed session is not a seat session
    assert upstreams[0].requests == []
