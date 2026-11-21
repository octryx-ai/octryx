"""Outlook schedule helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_MICROSOFT_GRAPH

from ..context import ToolContext
from .common import connection_http_json
from .outlook_core import (
    _outlook_calendar_window,
    _outlook_graph_base_url,
    _outlook_headers,
    _outlook_time_zone,
    _parse_iso_datetime,
)

#: This module's HTTP helpers use the microsoft_graph egress rule.
_http_json = connection_http_json(CONNECTION_MICROSOFT_GRAPH)


async def _get_outlook_schedule(
    context: ToolContext,
    *,
    mailbox: str,
    schedules: list[str],
    params: dict[str, Any],
) -> dict[str, Any]:
    start, end = _outlook_calendar_window(context, params)
    headers = await _outlook_headers(context)
    data = await _http_json(
        "POST",
        f"{_outlook_graph_base_url(context)}/users/{quote(mailbox, safe='')}/calendar/getSchedule",
        headers={**headers, "Content-Type": "application/json"},
        json_body={
            "schedules": schedules,
            "startTime": {"dateTime": start, "timeZone": _outlook_time_zone(context, params)},
            "endTime": {"dateTime": end, "timeZone": _outlook_time_zone(context, params)},
            "availabilityViewInterval": int(params.get("interval_minutes") or 30),
        },
    )
    return {"mailbox": mailbox, "start": start, "end": end, "schedules": data.get("value") or []}


def _collect_busy_ranges(schedule_items: list[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
    ranges: list[tuple[datetime, datetime]] = []
    for item in schedule_items:
        start_dt = _parse_iso_datetime((item.get("start") or {}).get("dateTime"))
        end_dt = _parse_iso_datetime((item.get("end") or {}).get("dateTime"))
        if start_dt and end_dt and end_dt > start_dt:
            ranges.append((start_dt, end_dt))
    ranges.sort(key=lambda value: value[0])
    return ranges
