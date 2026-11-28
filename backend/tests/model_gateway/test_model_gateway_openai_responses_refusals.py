"""The OpenAI Responses route refuses a foreign served model, secrets, an ungranted alias, a foreign-audience token, an exhausted budget, a changing content obligation, a body without input and a workspace without Codex before anything is dispatched."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from app.models import TurnTrace
from app.services.oauth_provider.tokens import DEFAULT_RESOURCE_AUDIENCE
from tests.content_security.gateway_route_support import configure
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.model_gateway_openai_responses_support import ROUTE, _body, responses_setup  # noqa: F401

from .conftest import ALIAS
from .test_inbound_anthropic_gateway import AWS_KEY_LOOKALIKE
from .test_inbound_budget_and_pricing import _spend_today


def _assert_refused(response: httpx.Response, status: int, reason: str, error_type: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["x-octryx-gateway-reason"] == reason
    error = response.json()["error"]
    assert (error["code"], error["type"]) == (reason, error_type)
    assert reason in error["message"]
    return error


async def test_a_served_model_outside_the_alias_is_refused_before_anything_is_forwarded(client, db,
                                                                                       responses_setup):  # noqa: F811
    fake, build = responses_setup
    fake.model = "some-unadmitted-fallback"

    response = await client.post(ROUTE, json=_body(), headers=await build())

    _assert_refused(response, 502, "served_model_not_admitted", "server_error")
    assert "some-unadmitted-fallback" not in response.text
    assert response.headers["x-should-retry"] == "false"


async def test_a_secret_in_the_newest_turn_is_refused_before_dispatch(client, db, responses_setup):  # noqa: F811
    fake, build = responses_setup
    headers = await build()
    await configure(db, headers["X-Octryx-Workspace"], "secrets", "refuse")  # the default masks

    response = await client.post(ROUTE, json=_body(newest=f"use {AWS_KEY_LOOKALIKE}"), headers=headers)

    _assert_refused(response, 400, "secret_detected_in_prompt", "invalid_request_error")
    assert AWS_KEY_LOOKALIKE not in response.text
    assert fake.requests == []
    assert (await db.execute(select(TurnTrace))).scalars().all() == []


async def test_a_secret_in_a_tool_output_is_refused_too(client, db, responses_setup):  # noqa: F811
    fake, build = responses_setup
    headers = await build()
    await configure(db, headers["X-Octryx-Workspace"], "secrets", "refuse")
    body = _body()
    body["input"] = body["input"][:4]
    body["input"][3]["output"] = [{"type": "input_text", "text": f"key {AWS_KEY_LOOKALIKE}"}]

    response = await client.post(ROUTE, json=body, headers=headers)

    _assert_refused(response, 400, "secret_detected_in_prompt", "invalid_request_error")
    assert fake.requests == []


async def test_an_alias_the_workspace_has_not_granted_is_denied_before_dispatch(client, responses_setup):  # noqa: F811
    fake, build = responses_setup

    response = await client.post(ROUTE, json=_body(), headers=await build(allowed_aliases=("some-other-alias",)))

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "permission_error"
    assert response.headers["x-octryx-gateway-state"] == "denied"
    assert fake.requests == []


async def test_a_token_minted_for_another_audience_is_unauthorized(client, responses_setup):  # noqa: F811
    fake, build = responses_setup

    response = await client.post(ROUTE, json=_body(), headers=await build(audience=DEFAULT_RESOURCE_AUDIENCE))

    _assert_refused(response, 401, "gateway_token_invalid", "authentication_error")
    assert fake.requests == []


async def test_an_exhausted_daily_budget_is_refused_before_dispatch(client, db, responses_setup):  # noqa: F811
    fake, build = responses_setup
    headers = await build()
    await _spend_today(db, "200.00")

    response = await client.post(ROUTE, json=_body(), headers=headers)

    _assert_refused(response, 403, "gateway_daily_budget_exhausted", "permission_error")
    assert fake.requests == []


async def test_a_body_without_input_is_refused(client, responses_setup):  # noqa: F811
    fake, build = responses_setup

    response = await client.post(ROUTE, json={"model": ALIAS, "messages": []}, headers=await build())

    error = _assert_refused(response, 400, "request_body_invalid", "invalid_request_error")
    assert "OpenAI Responses" in error["message"]
    assert fake.requests == []


async def test_a_workspace_that_does_not_allow_codex_refuses_the_route(client, db, responses_setup):  # noqa: F811
    from app.models import Project

    fake, build = responses_setup
    headers = await build()
    project = await db.get(Project, headers["X-Octryx-Workspace"])
    config = dict(project.config or {})
    config["agent_gateway_policy"] = {**(config.get("agent_gateway_policy") or {}),
                                      "engines": {"allowed": ["claude_code"]}}
    project.config = config
    await db.commit()

    response = await client.post(ROUTE, json=_body(), headers=headers)

    _assert_refused(response, 403, "engine_not_allowed_in_workspace", "permission_error")
    assert fake.requests == []
