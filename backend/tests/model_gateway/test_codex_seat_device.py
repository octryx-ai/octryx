"""Codex seat calls sent from the device ("server admits, Mac sends", ``seat_traffic: device``).

The launcher's seat proxy asks ``/seat/admit`` (the relay route's own checks), sends the admitted body to ChatGPT
itself and reports the answer to ``/seat/report``, which writes what the relay route writes for the same answer.
No ChatGPT call is made here: the device's upstream is the launcher's (``clients/octryx-claude``), and the relay
route's answer in the comparison comes from the same fake as in ``test_codex_seat``.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.models import (
    AgentPresence,
    AuditLog,
    DistributedLock,
    Message,
    Project,
    SystemConfig,
    ToolCall,
    TurnTrace,
    UsageEvent,
)
from app.services.agent_gateway.seat_traffic import SEAT_TRAFFIC_GATEWAY, SEAT_TRAFFIC_KEY
from app.services.model_gateway.inbound import codex_seat_upstream
from app.services.observability import agent_metrics
from app.time_utils import utc_now
from tests.model_gateway.codex_seat_device_support import ADMIT, REPORT, _admit, _device, _report
from tests.model_gateway.codex_seat_support import (
    CODEX_POLICY,
    CODEX_SESSION,
    MODEL,
    ROUTE,
    STREAM,
    FakeChatGPT,
    _body,
    _codex_session,
    _headers,
    _reason,
)


async def _rows(db, user_id: str) -> dict[str, Any]:
    """What a seat call wrote, without ids, times and the device's own marks."""
    [usage] = (await db.execute(select(UsageEvent).where(UsageEvent.user_id == user_id))).scalars().all()
    calls = (await db.execute(select(ToolCall).where(ToolCall.session_id == usage.session_id))).scalars().all()
    messages = (await db.execute(select(Message).where(Message.session_id == usage.session_id))).scalars().all()
    [trace] = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == usage.session_id))).scalars().all()
    presence = (await db.execute(select(AgentPresence).where(AgentPresence.user_id == user_id))).scalar_one()
    await db.refresh(presence)
    kept = {key: value for key, value in trace.usage_json.items()
            if key not in ("duration_ms", "seat_traffic", "seat_report")}
    return {
        "usage": (usage.provider, usage.model, usage.tokens_in, usage.tokens_out, usage.cache_read_tokens,
                  float(usage.cost), usage.cost_source, usage.request_id, usage.dispatch_owner),
        "tool_calls": sorted((call.request_id, call.tool_name, call.status, json.dumps(call.parameters, sort_keys=True))
                             for call in calls),
        "messages": sorted((item.role, item.content) for item in messages),
        "trace": (trace.provider, trace.model, kept, trace.context_snapshot_json),
        "allowance": (presence.five_hour_pct, presence.model),
    }


# --- admit + report write what the route writes -------------------------------------------------------------


@pytest.mark.asyncio
async def test_admit_returns_the_admitted_body_and_a_ticket_and_the_report_writes_what_the_route_writes(
        client, db, monkeypatch):
    agent_metrics.reset()
    _ws, device_user, gateway, credential = await _codex_session(client, db)
    headers = _device(gateway, credential)
    assert "authorization" not in headers  # the device never shows the platform its ChatGPT login

    admitted = await client.post(ADMIT, json=_body(), headers=headers)

    assert admitted.status_code == 200, admitted.text
    answer = admitted.json()
    assert answer["body"] == _body() and answer["notice"] == "" and answer["expires_in"] == 900
    assert len(answer["ticket"]) >= 40
    [ticket] = (await db.execute(select(DistributedLock))).scalars().all()
    assert answer["ticket"] not in ticket.lock_key and ticket.is_active  # only its hash is stored
    reported = await _report(client, gateway, credential, answer)
    assert reported.status_code == 200 and reported.json() == {"recorded": True, "mismatch": []}
    device = await _rows(db, device_user)
    [trace] = (await db.execute(select(TurnTrace).where(TurnTrace.provider == "openai_codex_seat"))).scalars().all()
    assert trace.usage_json["seat_traffic"] == "device"
    assert trace.usage_json["seat_report"] == {"mismatch": [], "truncated": False}

    # The same call through the relay route (``seat_traffic: gateway``) writes the same rows.
    fake = FakeChatGPT()
    monkeypatch.setattr(codex_seat_upstream, "codex_seat_transport", lambda: httpx.MockTransport(fake.handle))
    monkeypatch.delenv(codex_seat_upstream.CODEX_SEAT_UPSTREAM_ENV, raising=False)
    db.add(SystemConfig(key=SEAT_TRAFFIC_KEY, value=SEAT_TRAFFIC_GATEWAY))
    await db.commit()
    _ws2, route_user, gateway2, credential2 = await _codex_session(client, db)
    relayed = await client.post(ROUTE, json=_body(), headers=_headers(gateway2, credential2))
    assert relayed.status_code == 200 and relayed.text == STREAM

    assert device == await _rows(db, route_user)
    # On /metrics the two ways stay apart (route), with the same tokens.
    metrics = "\n".join(agent_metrics.render())
    for route in ("device_report", "gateway"):
        labels = f'provider="openai_codex_seat",model="{MODEL}",route="{route}"'
        assert f'octryx_llm_requests_total{{{labels},outcome="ok"}} 1' in metrics
        assert f'octryx_llm_tokens_total{{{labels},type="output",engine="codex",' in metrics
    assert 'octryx_seat_admit_total{engine="codex",outcome="admitted",reason="none"} 1' in metrics
    assert device["tool_calls"][0][:3] == ("call_1", "Bash", "success")  # exec evidence reads these rows
    assert device["trace"][3]["codex_session_id"] == CODEX_SESSION
    assert device["allowance"] == (12.5, MODEL)


@pytest.mark.asyncio
async def test_a_non_streamed_answer_and_an_upstream_error_are_handled_like_the_route(client, db):
    agent_metrics.reset()
    _ws, user_id, gateway, credential = await _codex_session(client, db)
    admitted = (await _admit(client, gateway, credential, _body(stream=False))).json()
    error = await _report(client, gateway, credential, admitted, status=429,
                          stream=json.dumps({"error": {"type": "usage_limit_reached"}}),
                          headers={"retry-after": "60", "x-codex-primary-used-percent": "100"})
    assert error.json() == {"recorded": False, "mismatch": []}  # relayed, not recorded (the route's rule)
    presence = (await db.execute(select(AgentPresence).where(AgentPresence.user_id == user_id))).scalar_one()
    await db.refresh(presence)
    assert presence.five_hour_pct == 100.0  # but the allowance is kept, as on the route

    answer = {"id": "resp_json", "model": MODEL, "status": "completed", "usage": {"input_tokens": 10,
              "output_tokens": 2}, "output": [{"type": "message", "role": "assistant",
                                               "content": [{"type": "output_text", "text": "Done."}]}]}
    admitted = (await _admit(client, gateway, credential, _body(stream=False))).json()
    ok = await _report(client, gateway, credential, admitted, stream=json.dumps(answer))
    assert ok.json() == {"recorded": True, "mismatch": []}
    [usage] = (await db.execute(select(UsageEvent).where(UsageEvent.user_id == user_id))).scalars().all()
    assert (usage.tokens_in, usage.tokens_out) == (10, 2)
    # The upstream error is a request too (never usage), the recorded answer one more.
    metrics = "\n".join(agent_metrics.render())
    labels = f'provider="openai_codex_seat",model="{MODEL}",route="device_report"'
    assert f'octryx_llm_requests_total{{{labels},outcome="error"}} 1' in metrics
    assert f'octryx_llm_requests_total{{{labels},outcome="ok"}} 1' in metrics


# --- admit refuses exactly like the route --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admit_refuses_like_the_route_and_issues_no_ticket(client, db, monkeypatch):
    from app.services.workflow_runs.octryx import model_guard

    agent_metrics.reset()
    workspace_id, _user, gateway, credential = await _codex_session(
        client, db, policy={**CODEX_POLICY, "codex_seat_models": ["gpt-6.1-sol", MODEL]})
    secret = await _admit(client, gateway, credential, _body(newest="key AKIA" + "ABCDEFGHIJKLMNOP"))
    other_model = await _admit(client, gateway, credential, {**_body(), "model": "gpt-6-astra"})

    async def budget_used_up(_db, _session_id, body, field="model", *, engine=""):
        return model_guard.GuardResult(body, model_guard.REASON_RUN_BUDGET, "The run reached its model budget.")

    monkeypatch.setattr(model_guard, "guard_model_call", budget_used_up)
    budget = await _admit(client, gateway, credential)
    monkeypatch.undo()
    project = await db.get(Project, workspace_id)
    project.config = {**project.config, "agent_gateway_policy": {"codex_seat_mode": "forbidden"}}
    await db.commit()
    forbidden = await _admit(client, gateway, credential)

    assert (secret.status_code, _reason(secret)) == (400, "secret_detected_in_prompt")
    assert (other_model.status_code, _reason(other_model)) == (403, "seat_model_not_allowed")
    assert (budget.status_code, _reason(budget)) == (403, model_guard.REASON_RUN_BUDGET)
    assert (forbidden.status_code, _reason(forbidden)) == (403, "codex_seat_mode_forbidden")
    assert secret.headers["x-octryx-gateway-reason"] == "secret_detected_in_prompt"  # the route's shape
    assert (await db.execute(select(func.count()).select_from(DistributedLock))).scalar_one() == 0
    metrics = "\n".join(agent_metrics.render())
    for reason in ("secret_detected_in_prompt", "seat_model_not_allowed", "codex_seat_mode_forbidden"):
        assert f'octryx_seat_admit_total{{engine="codex",outcome="refused",reason="{reason}"}} 1' in metrics


# --- tickets ----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_used_expired_foreign_or_missing_ticket_is_refused_and_writes_nothing(client, db):
    _ws, _user, gateway, credential = await _codex_session(client, db)
    _ws2, _other, gateway2, credential2 = await _codex_session(client, db)
    first = (await _admit(client, gateway, credential)).json()
    assert (await _report(client, gateway, credential, first)).status_code == 200
    await db.execute(UsageEvent.__table__.delete())
    await db.commit()

    reused = await _report(client, gateway, credential, first)
    expired_ticket = (await _admit(client, gateway, credential)).json()
    for row in (await db.execute(select(DistributedLock).where(DistributedLock.is_active.is_(True)))).scalars():
        row.expires_at = utc_now() - timedelta(seconds=1)
    await db.commit()
    expired = await _report(client, gateway, credential, expired_ticket)
    foreign_ticket = (await _admit(client, gateway, credential)).json()
    foreign = await _report(client, gateway2, credential2, foreign_ticket)
    missing = await _report(client, gateway, credential, {**foreign_ticket, "ticket": ""})
    no_credential = await client.post(REPORT, json={}, headers={
        "x-octryx-session": gateway["x-octryx-session"]})

    assert [(item.status_code, _reason(item)) for item in (reused, expired, foreign, missing)] == [
        (403, "seat_ticket_used"), (403, "seat_ticket_expired"), (403, "seat_ticket_foreign_session"),
        (403, "seat_ticket_invalid")]
    assert no_credential.status_code == 401
    assert (await db.execute(select(func.count()).select_from(UsageEvent))).scalar_one() == 0
    # The foreign attempt did not burn the ticket: its own session still reports it.
    assert (await _report(client, gateway, credential, foreign_ticket)).json()["recorded"] is True


@pytest.mark.asyncio
async def test_a_report_of_another_body_is_refused_with_a_mismatch_event(client, db):
    _ws, user_id, gateway, credential = await _codex_session(client, db)
    admitted = (await _admit(client, gateway, credential)).json()

    tampered = await _report(client, gateway, credential, {**admitted, "body": _body(newest="Something else.")})

    assert (tampered.status_code, _reason(tampered)) == (403, "seat_ticket_body_mismatch")
    [event] = (await db.execute(select(AuditLog).where(
        AuditLog.action == "model_gateway.codex_seat.seat_report_mismatch"))).scalars().all()
    assert event.details == {"fields": ["body"], "model": MODEL} and event.user_id == user_id
    assert (await db.execute(select(func.count()).select_from(UsageEvent))).scalar_one() == 0
