"""Outlook calendar connector tools and connection test, and the ServiceNow record table guardrail."""

# ruff: noqa: F401,I001,E501

import asyncio
import json
import uuid
import pytest
from sqlalchemy import select
from app.models import Approval, Session, User
from app.services.approval import resolve_approval_request
from app.services import connector_test_service as connector_test_service_module
from app.services.connector_test_service import run_connector_connection_test
from app.tools.connectors import common as connector_common
from app.tools.connectors import outlook_core
from app.tools.registry import execute_tool
from app.tools.context import ToolContext


_GRAPH_SCHEDULES = {
    "value": [
        {
            "scheduleId": "alice@example.com",
            "availabilityView": "0011",
            "scheduleItems": [
                {
                    "status": "busy",
                    "start": {"dateTime": "2026-04-01T09:00:00+00:00"},
                    "end": {"dateTime": "2026-04-01T10:00:00+00:00"},
                }
            ],
        },
        {
            "scheduleId": "bob@example.com",
            "availabilityView": "0001",
            "scheduleItems": [
                {
                    "status": "busy",
                    "start": {"dateTime": "2026-04-01T10:00:00+00:00"},
                    "end": {"dateTime": "2026-04-01T10:30:00+00:00"},
                }
            ],
        },
    ]
}

_GRAPH_CALENDAR_VIEW = {
    "value": [
        {
            "id": "evt-1",
            "subject": "Architecture Sync",
            "showAs": "busy",
            "start": {"dateTime": "2026-04-01T09:00:00+00:00"},
            "end": {"dateTime": "2026-04-01T09:30:00+00:00"},
            "attendees": [{"emailAddress": {"address": "bob@example.com"}, "type": "required"}],
        },
        {
            "id": "evt-2",
            "subject": "Out of Office",
            "showAs": "oof",
            "start": {"dateTime": "2026-04-01T12:00:00+00:00"},
            "end": {"dateTime": "2026-04-01T16:00:00+00:00"},
            "attendees": [],
        },
    ]
}


async def _fake_token(_context, *, scope):
    assert scope == "https://graph.microsoft.com/.default"
    return "graph-token"


async def _fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
    assert headers is not None
    if url.endswith("/calendar/getSchedule"):
        return _GRAPH_SCHEDULES
    if "/calendarView" in url:
        return _GRAPH_CALENDAR_VIEW
    if url.endswith("/events") and method == "POST":
        return {
            "id": "evt-created",
            "subject": json_body["subject"],
            "showAs": "busy",
            "start": json_body["start"],
            "end": json_body["end"],
            "attendees": json_body.get("attendees") or [],
            "location": json_body.get("location") or {},
            "webLink": "https://outlook.example.com/event/evt-created",
        }
    raise AssertionError(f"Unexpected Graph request: {method} {url}")


def _calendar_context(admin, session, db):
    return ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={
            "tool_policy": {"high_risk_grants": ["create_meeting", "send_meeting_invite"]},
            "outlook_default_mailbox": "alice@example.com",
            "outlook_allowed_mailboxes": ["alice@example.com", "bob@example.com"],
            "outlook_absence_mailboxes": ["alice@example.com"],
            "outlook_graph_url": "https://graph.microsoft.com/v1.0",
            "outlook_time_zone": "UTC",
        },
        capability_type="diagnosis",
        agent_mode_key="diagnosis",
        workspace_root=".",
        db=db,
    )


async def _approve(db, admin, blocked):
    approval = await db.execute(select(Approval).where(Approval.id == blocked["approval_id"]))
    approval_row = approval.scalar_one()
    await resolve_approval_request(
        db,
        approval_id=approval_row.id,
        resolved_by=admin.id,
        status="approved",
    )
    await db.commit()


async def _assert_free_busy_and_meetings(context):
    free_busy = await execute_tool(
        "get_free_busy",
        {
            "mailboxes": ["alice@example.com", "bob@example.com"],
            "start": "2026-04-01T09:00:00+00:00",
            "end": "2026-04-01T12:00:00+00:00",
        },
        context,
    )
    assert free_busy["count"] == 2

    meetings = await execute_tool(
        "list_meetings",
        {
            "mailbox": "alice@example.com",
            "start": "2026-04-01T08:00:00+00:00",
            "end": "2026-04-01T18:00:00+00:00",
        },
        context,
    )
    assert meetings["count"] == 2


async def _assert_next_slot_and_absence(context):
    next_slot = await execute_tool(
        "find_next_slot",
        {
            "mailboxes": ["alice@example.com", "bob@example.com"],
            "start": "2026-04-01T09:00:00+00:00",
            "end": "2026-04-01T12:00:00+00:00",
            "duration_minutes": 30,
        },
        context,
    )
    assert next_slot["found"] is True
    assert next_slot["start"] == "2026-04-01T10:30:00+00:00"

    absence = await execute_tool(
        "check_absence",
        {
            "mailbox": "alice@example.com",
            "start": "2026-04-01T08:00:00+00:00",
            "end": "2026-04-01T18:00:00+00:00",
        },
        context,
    )
    assert absence["is_absent"] is True


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_outlook_calendar_tools_cover_free_busy_meetings_creation_slots_and_absence(monkeypatch, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    monkeypatch.setattr(outlook_core, "_microsoft_graph_token", _fake_token)
    monkeypatch.setattr(connector_common, "_http_json", _fake_http_json)
    context = _calendar_context(admin, session, db)

    await _assert_free_busy_and_meetings(context)

    create_request = {
        "mailbox": "alice@example.com",
        "subject": "Roadmap Review",
        "start": "2026-04-01T13:00:00+00:00",
        "end": "2026-04-01T13:30:00+00:00",
        "attendees": ["bob@example.com"],
        "location": "Conf Room 1",
    }
    created_blocked = await execute_tool("create_meeting", create_request, context)
    assert created_blocked["approval_required"] is True
    assert created_blocked["change_preview"]["kind"] == "outlook_meeting"
    await _approve(db, admin, created_blocked)

    created = await execute_tool("create_meeting", create_request, context)
    assert created["created"] is True
    assert created["meeting"]["id"] == "evt-created"

    await _assert_next_slot_and_absence(context)

    invite_request = {
        "mailbox": "alice@example.com",
        "subject": "Invite Review",
        "start": "2026-04-01T15:00:00+00:00",
        "end": "2026-04-01T15:30:00+00:00",
        "attendees": ["bob@example.com"],
    }
    invite_blocked = await execute_tool("send_meeting_invite", invite_request, context)
    assert invite_blocked["approval_required"] is True
    assert invite_blocked["change_preview"]["kind"] == "outlook_meeting"
    await _approve(db, admin, invite_blocked)

    invite = await execute_tool("send_meeting_invite", invite_request, context)
    assert invite["status"] == "sent"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_outlook_calendar_connector_health_supports_native_connection_test(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            assert url.endswith("/users/alice@example.com/events")
            return FakeResponse(200, {"value": [{"id": "evt-1"}]})

    monkeypatch.setattr(connector_test_service_module.httpx, "AsyncClient", FakeClient)

    result = await run_connector_connection_test(
        "outlook_calendar",
        {
            "outlook_graph_url": "https://graph.microsoft.com/v1.0",
            "outlook_default_mailbox": "alice@example.com",
            "outlook_access_token": "token",
        },
    )
    assert result["ok"] is True
    assert result["summary"] == "Connected to Outlook calendar."
    assert result["counts"] == {"sample_events": 1}
    assert "alice@example.com" not in str(result)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_get_servicenow_record_blocks_disallowed_table():
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "servicenow_url": "https://company.service-now.com",
            "servicenow_token": "sn-token",
            "servicenow_allowed_tables": ["incident"],
        },
    )
    result = await execute_tool(
        "get_servicenow_record",
        {"table": "cmdb_ci", "sys_id": "abc123"},
        context,
    )
    assert "not allowed" in result["error"]
