"""Shared Outlook connector helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_MICROSOFT_GRAPH

from ..context import ToolContext
from .common import _headers_with_bearer, _limit, _normalize_string_list, _string, connection_http_json
from .microsoft_graph import _microsoft_graph_token

#: This module's HTTP helpers use the microsoft_graph egress rule.
_http_json = connection_http_json(CONNECTION_MICROSOFT_GRAPH)


def _outlook_graph_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("outlook_graph_url") or "https://graph.microsoft.com/v1.0").rstrip("/")


def _outlook_allowed_mailboxes(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("outlook_allowed_mailboxes"))


def _outlook_absence_mailboxes(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("outlook_absence_mailboxes"))


def _outlook_time_zone(context: ToolContext, params: dict[str, Any]) -> str:
    return _string(params.get("time_zone") or context.project_config.get("outlook_time_zone") or "UTC")


def _outlook_default_mailbox(context: ToolContext) -> str:
    return _string(context.project_config.get("outlook_default_mailbox"))


def _outlook_resolve_mailbox(context: ToolContext, params: dict[str, Any], *, allow_absence: bool = False) -> str:
    mailbox = _string(params.get("mailbox") or params.get("user") or _outlook_default_mailbox(context))
    allowed = _outlook_allowed_mailboxes(context)
    if allow_absence:
        allowed = list({*allowed, *_outlook_absence_mailboxes(context)})
    if not mailbox and len(allowed) == 1:
        mailbox = allowed[0]
    if not mailbox:
        raise ValueError("mailbox is required")
    if allowed and mailbox not in allowed:
        raise ValueError(f"mailbox '{mailbox}' is not allowed")
    return mailbox


def _iso_utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_iso_datetime(value: Any) -> datetime | None:
    raw = _string(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _outlook_calendar_window(context: ToolContext, params: dict[str, Any]) -> tuple[str, str]:
    start = _string(params.get("start") or params.get("start_datetime"))
    end = _string(params.get("end") or params.get("end_datetime"))
    if start and end:
        return start, end
    now = _iso_utc_now()
    start_dt = _parse_iso_datetime(start) or now
    end_dt = _parse_iso_datetime(end) or (start_dt + timedelta(days=1))
    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(hours=8)
    return start_dt.isoformat(), end_dt.isoformat()


async def _outlook_headers(context: ToolContext) -> dict[str, str]:
    token = await _microsoft_graph_token(context, scope="https://graph.microsoft.com/.default")
    return _headers_with_bearer(token, extra={"Accept": "application/json"})


def _normalize_outlook_event(item: dict[str, Any]) -> dict[str, Any]:
    organizer = (item.get("organizer") or {}).get("emailAddress") or {}
    location = item.get("location") or {}
    attendees = item.get("attendees") or []
    return {
        "id": item.get("id"),
        "subject": item.get("subject"),
        "start": (item.get("start") or {}).get("dateTime"),
        "end": (item.get("end") or {}).get("dateTime"),
        "show_as": item.get("showAs"),
        "is_all_day": bool(item.get("isAllDay")),
        "is_online_meeting": bool(item.get("isOnlineMeeting")),
        "web_link": item.get("webLink"),
        "organizer": organizer.get("address") or organizer.get("name"),
        "location": location.get("displayName"),
        "attendees": [
            {
                "name": ((attendee.get("emailAddress") or {}).get("name")),
                "address": ((attendee.get("emailAddress") or {}).get("address")),
                "type": attendee.get("type"),
                "status": ((attendee.get("status") or {}).get("response")),
            }
            for attendee in attendees
        ],
    }


async def _list_outlook_events(context: ToolContext, *, mailbox: str, params: dict[str, Any]) -> dict[str, Any]:
    start, end = _outlook_calendar_window(context, params)
    headers = await _outlook_headers(context)
    data = await _http_json(
        "GET",
        f"{_outlook_graph_base_url(context)}/users/{quote(mailbox, safe='')}/calendarView",
        headers=headers,
        params={
            "startDateTime": start,
            "endDateTime": end,
            "$top": _limit(context, params, default=20, maximum=100),
            "$orderby": "start/dateTime",
        },
    )
    events = data.get("value") or []
    return {
        "mailbox": mailbox,
        "start": start,
        "end": end,
        "count": len(events),
        "meetings": [_normalize_outlook_event(item) for item in events],
    }
