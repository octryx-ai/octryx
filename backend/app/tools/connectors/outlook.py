"""Outlook connector tools."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_MICROSOFT_GRAPH

from ...services.approval import ensure_approval_request
from ...services.change_preview import (
    build_change_request_fingerprint,
    consume_change_preview_grant,
    upsert_change_preview,
)
from ..context import ToolContext
from .common import _normalize_string_list, _string, connection_http_json
from .outlook_core import (
    _iso_utc_now,
    _list_outlook_events,
    _normalize_outlook_event,
    _outlook_graph_base_url,
    _outlook_headers,
    _outlook_resolve_mailbox,
    _outlook_time_zone,
    _parse_iso_datetime,
)
from .outlook_schedule import _collect_busy_ranges, _get_outlook_schedule

#: This module's HTTP helpers use the microsoft_graph egress rule.
_http_json = connection_http_json(CONNECTION_MICROSOFT_GRAPH)


def _outlook_meeting_window(params: dict[str, Any]) -> tuple[str, str]:
    start = _string(params.get("start") or params.get("start_datetime"))
    end = _string(params.get("end") or params.get("end_datetime"))
    return start, end


def _outlook_meeting_change_payload(tool_name: str, params: dict[str, Any], *, mailbox: str) -> dict[str, Any]:
    start, end = _outlook_meeting_window(params)
    attendees = _normalize_string_list(params.get("attendees"))
    return {
        "tool_name": tool_name,
        "mailbox": mailbox,
        "subject": _string(params.get("subject")),
        "start": start,
        "end": end,
        "attendee_count": len(attendees),
        "attendees": attendees,
        "location": _string(params.get("location")),
        "body_present": bool(_string(params.get("body"))),
        "online_meeting": bool(params.get("online_meeting")),
        "time_zone": _string(params.get("time_zone")),
    }


def _outlook_meeting_preview_payload(
    *,
    action_title: str,
    action_summary: str,
    mailbox: str,
    meeting_change: dict[str, Any],
) -> dict[str, Any]:
    details = [
        f"Mailbox: `{mailbox}`",
        f"Attendees: {int(meeting_change.get('attendee_count') or 0)}",
    ]
    if meeting_change.get("location"):
        details.append(f"Location: `{meeting_change['location']}`")
    if meeting_change.get("online_meeting"):
        details.append("Online meeting enabled.")
    if meeting_change.get("body_present"):
        details.append("Meeting body supplied.")
    return {
        "kind": "outlook_meeting",
        "title": action_title,
        "summary": action_summary,
        "mailbox": mailbox,
        "subject": meeting_change.get("subject") or "",
        "start": meeting_change.get("start") or "",
        "end": meeting_change.get("end") or "",
        "attendee_count": int(meeting_change.get("attendee_count") or 0),
        "details": details,
    }


async def _maybe_block_outlook_meeting_with_approval(
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
    *,
    action_title: str,
    action_summary: str,
) -> dict[str, Any] | None:
    mailbox = _outlook_resolve_mailbox(context, params)
    meeting_change = _outlook_meeting_change_payload(tool_name, params, mailbox=mailbox)
    if await consume_change_preview_grant(
        context.db,
        session_id=context.session_id,
        tool_name=tool_name,
        payload=meeting_change,
        context=context,
        mark_payload=params,
    ):
        return None
    if context.db is None or not context.user_id:
        return None
    preview_payload = _outlook_meeting_preview_payload(
        action_title=action_title,
        action_summary=action_summary,
        mailbox=mailbox,
        meeting_change=meeting_change,
    )
    approval = await ensure_approval_request(
        context.db,
        requested_by=context.user_id,
        session_id=context.session_id,
        action=f"Approve Outlook meeting change for {tool_name}",
        reason=preview_payload["summary"],
    )
    preview = await upsert_change_preview(
        context.db,
        tool_name=tool_name,
        preview_payload=preview_payload,
        request_fingerprint=build_change_request_fingerprint(tool_name, meeting_change),
        session_id=context.session_id,
        approval_id=approval.id,
    )
    return {
        "error": "Execution blocked pending Outlook approval.",
        "approval_required": True,
        "approval_id": approval.id,
        "approval_status": approval.status,
        "change_preview_id": preview.id,
        "change_preview": preview_payload,
        "tool_name": tool_name,
    }


async def _create_outlook_meeting(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    mailbox = _outlook_resolve_mailbox(context, params)
    subject = _string(params.get("subject"))
    start = _string(params.get("start") or params.get("start_datetime"))
    end = _string(params.get("end") or params.get("end_datetime"))
    if not subject or not start or not end:
        return {"error": "subject, start and end are required"}
    attendees = _normalize_string_list(params.get("attendees"))
    headers = await _outlook_headers(context)
    payload = {
        "subject": subject,
        "body": {
            "contentType": "HTML" if bool(params.get("body_html")) else "Text",
            "content": _string(params.get("body") or ""),
        },
        "start": {"dateTime": start, "timeZone": _outlook_time_zone(context, params)},
        "end": {"dateTime": end, "timeZone": _outlook_time_zone(context, params)},
        "location": {"displayName": _string(params.get("location"))},
        "attendees": [{"emailAddress": {"address": address}, "type": "required"} for address in attendees],
        "isOnlineMeeting": bool(params.get("online_meeting")),
    }
    data = await _http_json(
        "POST",
        f"{_outlook_graph_base_url(context)}/users/{quote(mailbox, safe='')}/events",
        headers={**headers, "Content-Type": "application/json"},
        json_body={key: value for key, value in payload.items() if value not in ("", [], {}, None)},
    )
    return {"mailbox": mailbox, "meeting": _normalize_outlook_event(data), "created": True}


class GetOutlookFreeBusyTool:
    name = "get_free_busy"
    description = "Read free/busy information for configured Outlook or Exchange mailboxes."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        mailbox = _outlook_resolve_mailbox(context, params)
        schedules = _normalize_string_list(params.get("mailboxes")) or [mailbox]
        result = await _get_outlook_schedule(context, mailbox=mailbox, schedules=schedules, params=params)
        return {
            "mailbox": mailbox,
            "start": result["start"],
            "end": result["end"],
            "count": len(result["schedules"]),
            "schedules": [
                {
                    "schedule_id": item.get("scheduleId"),
                    "availability_view": item.get("availabilityView"),
                    "schedule_items": item.get("scheduleItems") or [],
                }
                for item in result["schedules"]
            ],
        }


class ListOutlookMeetingsTool:
    name = "list_meetings"
    description = "List calendar meetings for a configured Outlook or Exchange mailbox."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        mailbox = _outlook_resolve_mailbox(context, params)
        return await _list_outlook_events(context, mailbox=mailbox, params=params)


class CreateOutlookMeetingTool:
    name = "create_meeting"
    description = "Create an Outlook or Exchange calendar meeting with approval gating."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        blocked = await _maybe_block_outlook_meeting_with_approval(
            self.name,
            params,
            context,
            action_title="Outlook meeting creation",
            action_summary=f"Create Outlook meeting: {_string(params.get('subject'))}",
        )
        if blocked is not None:
            return blocked
        return await _create_outlook_meeting(params, context)


class FindNextOutlookSlotTool:
    name = "find_next_slot"
    description = "Find the next free calendar slot across one or more Outlook or Exchange mailboxes."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        mailbox = _outlook_resolve_mailbox(context, params)
        schedules = _normalize_string_list(params.get("mailboxes")) or [mailbox]
        duration_minutes = max(15, int(params.get("duration_minutes") or 30))
        result = await _get_outlook_schedule(context, mailbox=mailbox, schedules=schedules, params=params)
        start_dt = _parse_iso_datetime(result["start"]) or _iso_utc_now()
        end_dt = _parse_iso_datetime(result["end"]) or (start_dt + timedelta(hours=8))
        cursor = start_dt
        busy_ranges: list[tuple[Any, Any]] = []
        for schedule in result["schedules"]:
            busy_ranges.extend(_collect_busy_ranges(schedule.get("scheduleItems") or []))
        busy_ranges.sort(key=lambda value: value[0])
        while cursor + timedelta(minutes=duration_minutes) <= end_dt:
            candidate_end = cursor + timedelta(minutes=duration_minutes)
            overlap = next((item for item in busy_ranges if cursor < item[1] and candidate_end > item[0]), None)
            if overlap is None:
                return {
                    "mailbox": mailbox,
                    "mailboxes": schedules,
                    "start": cursor.isoformat(),
                    "end": candidate_end.isoformat(),
                    "duration_minutes": duration_minutes,
                    "found": True,
                }
            cursor = max(cursor + timedelta(minutes=15), overlap[1])
        return {"mailbox": mailbox, "mailboxes": schedules, "found": False, "duration_minutes": duration_minutes}


class CheckOutlookAbsenceTool:
    name = "check_absence"
    description = "Check if a mailbox is marked as absent or out-of-office in Outlook or Exchange."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        mailbox = _outlook_resolve_mailbox(context, params, allow_absence=True)
        meetings = await _list_outlook_events(context, mailbox=mailbox, params=params)
        absent_items = [
            item
            for item in meetings["meetings"]
            if _string(item.get("show_as")).lower() == "oof"
            or any(
                term in _string(item.get("subject")).lower() for term in ("vacation", "urlaub", "out of office", "ooo")
            )
        ]
        return {
            "mailbox": mailbox,
            "is_absent": bool(absent_items),
            "count": len(absent_items),
            "entries": absent_items,
        }


class SendOutlookMeetingInviteTool:
    name = "send_meeting_invite"
    description = "Create and send a meeting invitation through Outlook or Exchange with approval gating."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _normalize_string_list(params.get("attendees")):
            return {"error": "attendees are required"}
        blocked = await _maybe_block_outlook_meeting_with_approval(
            self.name,
            params,
            context,
            action_title="Outlook meeting invite",
            action_summary=f"Send Outlook meeting invite: {_string(params.get('subject'))}",
        )
        if blocked is not None:
            return blocked
        created = await _create_outlook_meeting(params, context)
        if created.get("error"):
            return created
        return {"status": "sent", "mailbox": created["mailbox"], "meeting": created["meeting"]}
