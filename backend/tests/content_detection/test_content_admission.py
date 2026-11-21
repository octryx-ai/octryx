"""Content in Cedar at model admission: governed and seat routes, chat driver, shadow first."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import PolicyDecisionLog
from app.services.content_routing.chat import apply_chat_content, chat_content_decision
from app.services.content_routing.segments import chat_segments
from app.services.model_gateway.litellm.errors import LiteLLMGatewayError
from app.services.policy_engine.decision_log import flush_decision_log
from tests.agent_gateway.seat_presence_support import SEAT, _body, _found_anywhere, _seat_headers, _seat_session
from tests.agent_gateway.seat_upstream_support import anthropic  # noqa: F401 - fixture, see below
from tests.content_detection.content_admission_support import BLOCK_IBAN, IBAN
from tests.model_gateway.conftest import ALIAS, verified_admission
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture, see below
from tests.model_gateway.test_inbound_anthropic_gateway import AWS_KEY_LOOKALIKE, ROUTE, _request_body

# The two fixtures come from the folder's conftest too; a gate that selects only some files can leave this module
# without them ("fixture 'gateway_setup' not found"): imported here they are always its own.
from tests.policy_engine_support import use_custom_policies

BLOCK_SEAT_PII = ('@id("no-personal-data-on-seat")\nforbid (principal, action == Action::"call_model", resource)\n'
                  'when { context.route == "seat" && context.content.categories.contains("secrets") };')
#: C12F-08: the gateway's built-in kinds are credentials and credential assignments only (no IBAN there).
ASSIGNMENT = "Hunter2024x"
BLOCK_ASSIGNMENT = BLOCK_IBAN.replace('"iban"', '"credential_assignment"')


async def _records(db):
    await flush_decision_log(db)
    await db.commit()
    return list((await db.execute(select(PolicyDecisionLog))).scalars())


# --- segments ---------------------------------------------------------------------------------------------


def test_chat_segments_cover_system_messages_and_the_newest_turn():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "old"},
                {"role": "assistant", "content": "a"}, {"role": "tool", "content": "result"},
                {"role": "user", "content": [{"type": "text", "text": "now"}, {"type": "image_url"}]}]
    assert [(item.source, item.text) for item in chat_segments(messages)] == [
        ("system", "sys"), ("tool_result", "result"), ("prompt", "now"), ("document", "")]


# --- the governed route -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_records_the_custom_policy_with_counts_and_sends_the_request(client, db, gateway_setup):  # noqa: F811 - the fixture imported above
    fake, build = gateway_setup
    headers = await build()
    use_custom_policies(BLOCK_ASSIGNMENT, mode="shadow")
    response = await client.post(ROUTE, json=_request_body(newest_text=f"login password={ASSIGNMENT} failed"), headers=headers)
    assert response.status_code == 200, response.text
    assert len(fake.requests) == 1
    # The request's one record (the gateway's) states what Cedar would have done; Cedar writes none of its own.
    [record] = await _records(db)
    assert record.gate == "content_security" and record.outcome == "reported"
    assert record.obligation["cedar"] == {"policies": ["block-bank-data"], "would": "deny", "applied": "none"}
    assert record.obligation["outcome"] == "forwarded"
    assert [(item["id"], item["count"]) for item in record.content["detected"]] == [("credential_assignment", 1)]
    assert record.content["sources"] == ["request"] and record.resource == f"gateway governed:{ALIAS}"
    assert ASSIGNMENT not in str(record.content) + record.resource


@pytest.mark.asyncio
async def test_enforce_refuses_with_the_policy_and_counts_before_dispatch(client, db, gateway_setup):  # noqa: F811 - the fixture imported above
    fake, build = gateway_setup
    headers = await build()
    use_custom_policies(BLOCK_ASSIGNMENT, mode="enforce")
    response = await client.post(ROUTE, json=_request_body(newest_text=f"login password={ASSIGNMENT} failed"), headers=headers)
    assert response.status_code == 403
    assert response.headers["x-octryx-gateway-reason"] == "content_policy_denied"
    message = response.json()["error"]["message"]
    assert "block-bank-data" in message and "credential_assignment ×1" in message and ASSIGNMENT not in message
    assert fake.requests == []
    clean = await client.post(ROUTE, json=_request_body(newest_text="all good"), headers=headers)
    assert clean.status_code == 200


@pytest.mark.asyncio
async def test_secret_scan_is_the_generated_policy_and_keeps_its_refusal(client, db, gateway_setup):  # noqa: F811 - the fixture imported above
    fake, build = gateway_setup
    headers = await build()
    response = await client.post(ROUTE, json=_request_body(newest_text=f"use {AWS_KEY_LOOKALIKE}"), headers=headers)
    assert response.status_code == 400
    assert response.headers["x-octryx-gateway-reason"] == "secret_detected_in_prompt"
    assert fake.requests == []
    [record] = await _records(db)
    assert record.outcome == "denied" and record.determining == ["platform:secrets-never-leave"]
    assert record.obligation["stage"] == "content" and record.obligation["applied"] == {"secrets": "refuse"}
    assert record.content["kinds"] == ["aws_access_key_id"] and AWS_KEY_LOOKALIKE not in str(record.content)


@pytest.mark.asyncio
async def test_approved_alias_is_exempt_through_resource_approved_for(client, db, gateway_setup, monkeypatch):  # noqa: F811 - the fixture imported above
    fake, build = gateway_setup
    headers = await build()
    policy = BLOCK_ASSIGNMENT.replace(";", "\nunless { resource.approved_for.contains(\"secrets\") };")
    use_custom_policies(policy, mode="enforce")
    refused = await client.post(ROUTE, json=_request_body(newest_text=f"login password={ASSIGNMENT}"), headers=headers)
    assert refused.status_code == 403
    from app.services.model_gateway.litellm import alias_catalog

    original = alias_catalog._resolve_approved_categories
    monkeypatch.setattr(alias_catalog, "_resolve_approved_categories",
                        lambda raw: frozenset({"secrets"}) if raw is None else original(raw))
    allowed = await client.post(ROUTE, json=_request_body(newest_text=f"login password={ASSIGNMENT}"), headers=headers)
    assert allowed.status_code == 200, allowed.text


# --- the seat route ---------------------------------------------------------------------------------------


@pytest.mark.committed_db  # the seat call records in its own session (see test_seat_presence)
@pytest.mark.asyncio
async def test_seat_route_asks_call_model_with_route_seat(client, db, anthropic):  # noqa: F811 - the fixture imported above
    _workspace_id, _user_id, gateway, credential = await _seat_session(client, db)
    use_custom_policies(BLOCK_SEAT_PII, mode="enforce")
    refused = await client.post(SEAT, json=_body(text=f"login password={ASSIGNMENT}"), headers=_seat_headers(gateway, credential))
    assert refused.status_code == 403
    assert refused.headers["x-octryx-gateway-reason"] == "content_policy_denied"
    assert anthropic.requests == []
    clean = await client.post(SEAT, json=_body(text="fix it"), headers=_seat_headers(gateway, credential))
    assert clean.status_code == 200
    secret = await client.post(SEAT, json=_body(text=f"use {AWS_KEY_LOOKALIKE}"),
                               headers=_seat_headers(gateway, credential))
    assert secret.status_code == 400 and secret.headers["x-octryx-gateway-reason"] == \
        "secret_detected_in_prompt"
    records = await _records(db)
    assert sorted(row.obligation["stage"] for row in records) == ["cedar", "content"], "one record per refusal"
    assert {row.resource for row in records} == {"gateway seat:claude-sonnet-5"}
    assert await _found_anywhere(db, ASSIGNMENT) == []


# --- the chat driver --------------------------------------------------------------------------------------


def _chat_entry():
    from app.services.model_gateway.litellm.alias_catalog import resolve_alias_admission
    from tests.model_gateway.conftest import gateway_config

    return resolve_alias_admission(ALIAS, gateway_config()).entry


@pytest.mark.asyncio
async def test_chat_driver_check_shadow_then_enforce():
    admission, entry = verified_admission(ALIAS), _chat_entry()
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": f"iban {IBAN}"}]

    def admit(alias):
        raise AssertionError("no route in this policy")

    use_custom_policies(BLOCK_IBAN, mode="shadow")
    decision = chat_content_decision(admission, entry, messages)
    assert decision.refusal == "" and decision.comparison.outcome == "custom_policy"
    unchanged = await apply_chat_content(admission, entry, messages, admit=admit, tools=False)
    assert unchanged.messages == messages and unchanged.notice == {}
    use_custom_policies(BLOCK_IBAN, mode="enforce")
    with pytest.raises(LiteLLMGatewayError) as raised:
        await apply_chat_content(admission, entry, messages, admit=admit, tools=False)
    assert raised.value.denial_reason == "content_policy_denied"
    clean = [{"role": "user", "content": "nothing here"}]
    assert (await apply_chat_content(admission, entry, clean, admit=admit, tools=False)).messages == clean


def test_chat_driver_leaves_the_secret_policy_out():
    admission, entry = verified_admission(ALIAS), _chat_entry()
    use_custom_policies("", mode="enforce")
    decision = chat_content_decision(admission, entry, [{"role": "user", "content": f"use {AWS_KEY_LOOKALIKE}"}])
    assert decision.refusal == "" and decision.comparison.outcome == "match"
