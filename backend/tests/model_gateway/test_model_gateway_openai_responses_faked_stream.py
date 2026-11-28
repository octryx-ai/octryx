from __future__ import annotations

import json

from sqlalchemy import select

from app.models import TurnTrace, UsageEvent
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.model_gateway_openai_responses_support import (  # noqa: F401
    ROUTE,
    _body,
    responses_setup,
)

from .conftest import ALIAS, MODEL_GROUP


def _events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: {")]


async def test_a_faked_stream_reaches_codex_as_a_full_lifecycle_under_the_alias(client, db, responses_setup):  # noqa: F811
    fake, build = responses_setup
    fake.faked = "complete"

    response = await client.post(ROUTE, json=_body(), headers=await build())

    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert [event["type"] for event in events] == [
        "response.created",
        "response.output_item.added", "response.output_text.delta", "response.output_item.done",
        "response.output_item.added", "response.output_item.done",
        "response.completed"]
    assert events[0]["response"]["status"] == "in_progress" and events[0]["response"]["output"] == []
    assert events[0]["response"]["model"] == ALIAS and events[-1]["response"]["model"] == ALIAS
    assert MODEL_GROUP not in response.text
    assert events[1]["item"]["content"] == [] and events[2]["delta"] == "All tests pass."
    assert events[5]["item"]["call_id"] == "call_9"

    [usage] = (await db.execute(select(UsageEvent).where(UsageEvent.model == ALIAS))).scalars().all()
    assert (usage.tokens_out, usage.request_id) == (500, "req_up_3")
    [trace] = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == usage.session_id))).scalars().all()
    assert trace.usage_json["stream_completed"] is True and trace.usage_json["stop_reason"] == "tool_use"


async def test_a_faked_stream_of_another_model_is_refused_before_anything_reaches_codex(client, responses_setup):  # noqa: F811
    fake, build = responses_setup
    fake.faked = "complete"
    fake.model = "some-other-model"

    refused = await client.post(ROUTE, json=_body(), headers=await build())

    assert refused.status_code == 502
    assert refused.headers["x-octryx-gateway-reason"] == "served_model_not_admitted"


async def test_a_faked_stream_that_ends_without_its_completed_response_is_refused(client, responses_setup):  # noqa: F811
    fake, build = responses_setup
    fake.faked = "truncated"

    refused = await client.post(ROUTE, json=_body(), headers=await build())

    assert refused.status_code == 502
    assert refused.headers["x-octryx-gateway-reason"] == "stream_missing_response_created"
