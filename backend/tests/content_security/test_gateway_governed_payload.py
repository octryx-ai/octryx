"""The governed gateway sends exactly the payload its content check read (C12D-02).

A governed call's payload — the client's body with ``model`` replaced by the alias' model group and, on the Responses
route, the effective output cap — is built before the scan; the bytes the upstream receives are the serialization of
that very object. Asserted on the captured upstream for governed Messages, Responses, count-tokens and a company
model chosen in a Claude Code seat session.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx
import pytest

from app.services.content_routing import gateway_plan
from tests.content_security.gateway_route_support import ANTHROPIC_ROUTE, open_anthropic, open_responses
from tests.model_gateway.conftest import ALIAS, MODEL_GROUP
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.inbound_model_picker_support import OPT_IN, _workspace
from tests.model_gateway.model_gateway_openai_responses_support import responses_setup  # noqa: F401 - fixture
from tests.model_gateway.test_inbound_model_picker_seat import (  # noqa: F401 - fixture
    SEAT_COUNT,
    SEAT_MESSAGES,
    _body,
    _seat,
    upstreams,
)


@pytest.fixture
def checked(monkeypatch) -> list[dict[str, Any]]:
    """Every payload the gateway's content check read, as it read it."""
    seen: list[dict[str, Any]] = []
    real = gateway_plan.scan_request

    def spy(body, workspace_id, budget):
        seen.append(copy.deepcopy(dict(body)))
        return real(body, workspace_id, budget)

    monkeypatch.setattr(gateway_plan, "scan_request", spy)
    return seen


def _same(checked: list[dict[str, Any]], sent: list[httpx.Request]) -> None:
    [read], [request] = checked, sent
    assert read["model"] == MODEL_GROUP, "the mapped model group is part of what is checked"
    assert request.content == json.dumps(read, ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert json.loads(request.content) == read


async def test_governed_messages_send_the_checked_payload(client, db, gateway_setup, checked):  # noqa: F811
    route = await open_anthropic(gateway_setup)
    response = await client.post(route.path, json=route.body(), headers=route.headers)
    assert response.status_code == 200, response.text
    _same(checked, route.upstream)


async def test_governed_responses_send_the_checked_payload_with_its_output_cap(client, db, responses_setup,  # noqa: F811
                                                                            checked):
    route = await open_responses(responses_setup)
    posted = route.body()
    assert "max_output_tokens" not in posted
    response = await client.post(route.path, json=posted, headers=route.headers)
    assert response.status_code == 200, response.text
    _same(checked, route.upstream)
    assert ("max_output_tokens" in checked[0]) is ("max_output_tokens" in json.loads(route.upstream[0].content))


async def test_governed_count_tokens_send_the_checked_payload(client, db, gateway_setup, checked):  # noqa: F811
    fake, _build = gateway_setup
    route = await open_anthropic(gateway_setup)
    fake.handle = lambda request: (fake.requests.append(request), httpx.Response(200, json={"input_tokens": 7}))[1]
    response = await client.post(f"{ANTHROPIC_ROUTE}/count_tokens", json=route.body(), headers=route.headers)
    assert response.status_code == 200 and response.json() == {"input_tokens": 7}, response.text
    _same(checked, route.upstream)


@pytest.mark.parametrize("path", [SEAT_MESSAGES, SEAT_COUNT], ids=["messages", "count_tokens"])
async def test_a_seat_company_call_sends_the_checked_governed_payload(client, db, upstreams, checked, path):  # noqa: F811
    litellm, anthropic = upstreams
    _workspace_id, gateway = await _workspace(db, policy=OPT_IN)
    seat = await _seat(client, gateway)
    response = await client.post(path, json=_body(f"company/{ALIAS}"), headers=seat)
    assert response.status_code == 200, response.text
    assert anthropic.requests == []
    _same(checked, litellm.requests)
