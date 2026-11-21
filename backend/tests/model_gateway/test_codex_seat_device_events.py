"""Device seat reports that differ are marked and raise events, a missing report is recorded, seat traffic switches only by a platform admin, and standalone search and run-bound reports are recorded."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.models import AuditLog, TurnTrace, UsageEvent, WorkflowRunEvent
from app.services.model_gateway.inbound import codex_seat_device, codex_seat_tickets
from app.time_utils import utc_now
from tests.model_gateway.codex_seat_device_support import _admit, _device, _report
from tests.model_gateway.codex_seat_support import (
    CODEX_POLICY,
    CODEX_SESSION,
    MODEL,
    ROUTE,
    STREAM,
    _body,
    _codex_session,
    _headers,
    _reason,
)
from tests.policy_engine_support import bearer, make_user

SWITCH = "/api/v1/admin/seat-traffic"


async def _call(client, gateway, credential, **report: Any) -> httpx.Response:
    admitted = await _admit(client, gateway, credential)
    assert admitted.status_code == 200, admitted.text
    return await _report(client, gateway, credential, admitted.json(), **report)


SEARCH_ADMIT = "/api/v1/model-gateway/openai/seat/search-admit"


SEARCH_REPORT = "/api/v1/model-gateway/openai/seat/search-report"


# --- plausibility --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_model_a_seen_response_id_and_insane_usage_are_marked_and_raise_events(client, db):
    _ws, _user, gateway, credential = await _codex_session(client, db)
    assert (await _call(client, gateway, credential)).json() == {"recorded": True, "mismatch": []}

    duplicate = await _call(client, gateway, credential)  # the same answer (resp_1) reported again
    other = STREAM.replace(f'"model": "{MODEL}"', '"model": "gpt-6-astra"').replace("resp_1", "resp_2")
    swapped = await _call(client, gateway, credential, stream=other)
    insane = STREAM.replace('"output_tokens": 500', '"output_tokens": 1000000000000').replace("resp_1", "resp_3")
    huge = await _call(client, gateway, credential, stream=insane)
    dated = STREAM.replace(f'"model": "{MODEL}"', f'"model": "{MODEL}-2026-11-01"').replace("resp_1", "resp_4")
    snapshot = await _call(client, gateway, credential, stream=dated)

    assert duplicate.json() == {"recorded": True, "mismatch": ["response_id"]}
    assert swapped.json() == {"recorded": True, "mismatch": ["model"]}
    assert huge.json() == {"recorded": True, "mismatch": ["usage"]}
    assert snapshot.json() == {"recorded": True, "mismatch": []}  # a dated snapshot of the admitted model
    events = (await db.execute(select(AuditLog).where(
        AuditLog.action == "model_gateway.codex_seat.seat_report_mismatch"))).scalars().all()
    assert sorted(tuple(event.details["fields"]) for event in events) == [("model",), ("response_id",), ("usage",)]
    marks = sorted(tuple(trace.usage_json["seat_report"]["mismatch"]) for trace in (await db.execute(
        select(TurnTrace).where(TurnTrace.provider == "openai_codex_seat"))).scalars())
    assert marks == [(), (), ("model",), ("response_id",), ("usage",)]
    assert max(usage.tokens_out for usage in (await db.execute(select(UsageEvent))).scalars()) == (
        codex_seat_device.MAX_SANE_TOKENS)  # clamped, never summed as reported


@pytest.mark.asyncio
async def test_a_mismatch_of_a_run_bound_call_is_a_run_event(client, db, monkeypatch):
    from app.services.workflow_runs.records import new_chat_session, start_run
    from tests.knowledge_evidence_seed_support import seed_workspace
    from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased

    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    await db.commit()

    async def bound(_db, _session_id):
        return run.id

    monkeypatch.setattr(codex_seat_tickets, "_session_run_id", bound)
    _ws, _user, gateway, credential = await _codex_session(client, db)
    other = STREAM.replace(f'"model": "{MODEL}"', '"model": "gpt-6-astra"')

    assert (await _call(client, gateway, credential, stream=other)).json()["mismatch"] == ["model"]

    [event] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "seat_report_mismatch"))).scalars().all()
    assert event.detail["fields"] == ["model"] and event.detail["model"] == MODEL


@pytest.mark.asyncio
async def test_a_ticket_whose_report_never_came_is_a_seat_call_without_report(client, db):
    _ws, user_id, gateway, credential = await _codex_session(client, db)
    await _call(client, gateway, credential)  # reported: never flagged
    lost = (await _admit(client, gateway, credential)).json()

    assert await codex_seat_tickets.sweep_unreported_tickets(db) == 0  # still within its lifetime
    later = utc_now() + timedelta(seconds=codex_seat_tickets.TICKET_SECONDS + 1)
    assert await codex_seat_tickets.sweep_unreported_tickets(db, now=later) == 1
    assert await codex_seat_tickets.sweep_unreported_tickets(db, now=later) == 0  # flagged once

    [event] = (await db.execute(select(AuditLog).where(
        AuditLog.action == "model_gateway.codex_seat.seat_call_without_report"))).scalars().all()
    assert (event.user_id, event.details["model"], event.details["codex_session_id"]) == (
        user_id, MODEL, CODEX_SESSION)
    late = await _report(client, gateway, credential, lost)
    assert (late.status_code, _reason(late)) == (403, "seat_ticket_used")


# --- the switch -----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seat_traffic_is_device_by_default_only_a_platform_admin_switches_it_and_each_way_refuses_the_other(
        client, db):
    admin = await make_user(db, admin=True)
    member = await make_user(db, admin=False)
    await db.commit()
    _ws, _user, gateway, credential = await _codex_session(client, db)

    assert (await client.get(SWITCH, headers=bearer(member))).json() == {
        "seat_traffic": "device", "modes": ["device", "gateway"], "can_edit": False}
    policy = await client.get("/api/v1/agent-gateway/client-policy", headers=gateway)
    assert policy.json()["codex_seat"]["seat_traffic"] == "device"
    relayed = await client.post(ROUTE, json=_body(), headers=_headers(gateway, credential))
    assert (relayed.status_code, _reason(relayed)) == (409, "codex_seat_traffic_device")
    assert (await client.put(SWITCH, json={"seat_traffic": "gateway"}, headers=bearer(member))).status_code == 403
    assert (await client.put(SWITCH, json={"seat_traffic": "mac"}, headers=bearer(admin))).status_code == 422
    in_flight = (await _admit(client, gateway, credential)).json()

    switched = await client.put(SWITCH, json={"seat_traffic": "gateway"}, headers=bearer(admin))

    assert switched.json() == {"seat_traffic": "gateway", "modes": ["device", "gateway"], "can_edit": True}
    admit = await _admit(client, gateway, credential)
    assert (admit.status_code, _reason(admit)) == (409, "codex_seat_traffic_gateway")
    # The call admitted before the switch already left the device: its report is still recorded.
    assert (await _report(client, gateway, credential, in_flight)).json() == {"recorded": True, "mismatch": []}
    [audit] = (await db.execute(select(AuditLog).where(
        AuditLog.action == "admin.agent_gateway.seat_traffic_updated"))).scalars().all()
    assert audit.details == {"before": "device", "after": "gateway"}


async def test_codex_standalone_search_is_admitted_where_the_workspace_allows_the_web_and_recorded(client, db):
    """The gpt-6 models are Responses Lite and search with Codex's standalone web.run, sent by the device's seat
    proxy to ChatGPT's alpha/search. The platform records each search with its commands, and a completed one is
    web_search evidence. Open by default; ``tool_defaults.web_tools: off`` closes it."""
    from app.models import ToolCall
    from app.services.workflow_runs.octryx.stop_evidence import phase_evidence

    search = {"commands": [{"type": "search", "query": "SCA brewing control chart"}], "model": "gpt-6.1-sol"}
    _ws, _user, gateway, credential = await _codex_session(
        client, db, policy={**CODEX_POLICY, "device_runs": {"tool_defaults": {"web_tools": "off"}}})
    closed = await client.post(SEARCH_ADMIT, json=search, headers=_device(gateway, credential))
    assert closed.status_code == 403 and "seat_search_not_research_phase" in closed.text
    assert (await db.execute(select(func.count()).select_from(ToolCall))).scalar_one() == 0

    _ws, _user, gateway, credential = await _codex_session(client, db)
    headers = _device(gateway, credential)
    assert (await client.post(SEARCH_ADMIT, json={"commands": []}, headers=headers)).status_code == 400
    admitted = await client.post(SEARCH_ADMIT, json=search, headers=headers)
    assert admitted.status_code == 200, admitted.text
    ticket = admitted.json()["ticket"]
    row = await db.get(ToolCall, ticket)
    assert (row.tool_name, row.status) == ("codex_web_run", "pending") and "SCA brewing" in row.parameters["commands"]
    reported = await client.post(SEARCH_REPORT, json={"ticket": ticket, "status_code": 200}, headers=headers)
    assert reported.status_code == 200
    again = await client.post(SEARCH_REPORT, json={"ticket": ticket, "status_code": 200}, headers=headers)
    assert again.status_code == 403  # a ticket is used once
    await db.refresh(row)
    row.created_at = utc_now()
    assert [(use.name, use.succeeded) for use in phase_evidence([row], since=None, test_prefixes=()).tools] == [
        ("web_search", True)]


@pytest.mark.asyncio
async def test_a_run_bound_report_whose_request_already_carries_the_run_is_recorded(client, db, monkeypatch):
    """The session of a run carries "run" in its request attribution; a report that passed "run" twice would answer
    500 every time, record no seat call and count none of the Codex exec calls as evidence."""
    from app.services.observability import attribution
    from app.services.workflow_runs.records import new_chat_session, start_run
    from tests.knowledge_evidence_seed_support import seed_workspace
    from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased

    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    await db.commit()

    async def bound(_db, _session_id):
        return run.id

    monkeypatch.setattr(codex_seat_tickets, "_session_run_id", bound)
    monkeypatch.setattr(attribution, "current", lambda: {"run": run.id, "role": "octryx", "workspace": workspace_id})
    _ws, _user, gateway, credential = await _codex_session(client, db)

    reported = await _call(client, gateway, credential)

    assert reported.status_code == 200, reported.text
    assert reported.json() == {"recorded": True, "mismatch": []}
