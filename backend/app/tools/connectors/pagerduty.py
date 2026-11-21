"""PagerDuty incident connector tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_PAGERDUTY

from ..context import ToolContext
from .common import _limit, _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the pagerduty egress rule.
_http_json = connection_http_json(CONNECTION_PAGERDUTY)


def _pagerduty_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("pagerduty_url") or "https://api.pagerduty.com").rstrip("/")


def _pagerduty_headers(context: ToolContext, *, include_from: str | None = None) -> dict[str, str]:
    token = _string(context.project_config.get("pagerduty_token"))
    headers = {
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Token token={token}"
    from_value = _string(include_from or context.project_config.get("pagerduty_from_email"))
    if from_value:
        headers["From"] = from_value
    return headers


def _resolve_allowed_identifier(value: Any, *, allowed: list[str]) -> str | None:
    candidate = _string(value)
    if not candidate and len(allowed) == 1:
        candidate = allowed[0]
    if not candidate:
        return None
    if allowed and candidate not in allowed:
        return None
    return candidate


def _pagerduty_service_id(context: ToolContext, params: dict[str, Any]) -> str | None:
    return _resolve_allowed_identifier(
        params.get("service_id"), allowed=_normalize_string_list(context.project_config.get("pagerduty_service_ids"))
    )


def _pagerduty_schedule_id(context: ToolContext, params: dict[str, Any]) -> str | None:
    return _resolve_allowed_identifier(
        params.get("schedule_id"), allowed=_normalize_string_list(context.project_config.get("pagerduty_schedule_ids"))
    )


def _pagerduty_escalation_policy_id(context: ToolContext, params: dict[str, Any]) -> str | None:
    return _resolve_allowed_identifier(
        params.get("escalation_policy_id"),
        allowed=_normalize_string_list(context.project_config.get("pagerduty_escalation_policy_ids")),
    )


def _pagerduty_reference(identifier: str, type_name: str) -> dict[str, str]:
    return {"id": identifier, "type": type_name}


def _normalize_pagerduty_incident(incident: dict[str, Any]) -> dict[str, Any]:
    assignments = incident.get("assignments") or []
    return {
        "id": incident.get("id"),
        "incident_number": incident.get("incident_number"),
        "title": incident.get("title"),
        "status": incident.get("status"),
        "urgency": incident.get("urgency"),
        "html_url": incident.get("html_url"),
        "service": (incident.get("service") or {}).get("summary") or (incident.get("service") or {}).get("id"),
        "escalation_policy": (incident.get("escalation_policy") or {}).get("summary")
        or (incident.get("escalation_policy") or {}).get("id"),
        "assignees": [
            (assignment.get("assignee") or {}).get("summary") or (assignment.get("assignee") or {}).get("id")
            for assignment in assignments
            if assignment.get("assignee")
        ],
        "created_at": incident.get("created_at"),
        "updated_at": incident.get("updated_at"),
    }


class PagerDutyCreateIncidentTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        title = _string(params.get("title") or params.get("message"))
        if not title:
            return {"error": "title is required"}
        service_id = _pagerduty_service_id(context, params)
        if not service_id:
            return {"error": "service_id is required and must be allowed"}
        details = _string(params.get("details") or params.get("description"))
        urgency = _string(params.get("urgency") or "high").lower() or "high"
        payload = {
            "incident": {
                "type": "incident",
                "title": title,
                "service": _pagerduty_reference(service_id, "service_reference"),
                "urgency": urgency,
                "body": {"type": "incident_body", "details": details or title},
            }
        }
        escalation_policy_id = _pagerduty_escalation_policy_id(context, params)
        if escalation_policy_id:
            payload["incident"]["escalation_policy"] = _pagerduty_reference(
                escalation_policy_id, "escalation_policy_reference"
            )
        responder_ids = _normalize_string_list(params.get("assignee_ids") or params.get("responder_ids"))
        if responder_ids:
            payload["incident"]["assignments"] = [
                {"assignee": _pagerduty_reference(item, "user_reference")} for item in responder_ids
            ]
        data = await _http_json(
            "POST",
            f"{_pagerduty_base_url(context)}/incidents",
            headers=_pagerduty_headers(context, include_from=_string(params.get("from_email")) or None),
            json_body=payload,
        )
        return {
            "provider": "pagerduty",
            "incident": _normalize_pagerduty_incident(data.get("incident") or {}),
            "raw": data,
        }


class PagerDutyEscalateTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        incident_id = _string(params.get("incident_id") or params.get("alert_id"))
        if not incident_id:
            return {"error": "incident_id is required"}
        responder_ids = _normalize_string_list(params.get("responder_ids"))
        if not responder_ids:
            return {"error": "responder_ids is required for PagerDuty escalation"}
        message = _string(params.get("message") or "Escalation requested by Octryx")
        data = await _http_json(
            "POST",
            f"{_pagerduty_base_url(context)}/incidents/{quote(incident_id, safe='')}/responder_requests",
            headers=_pagerduty_headers(context, include_from=_string(params.get("from_email")) or None),
            json_body={
                "responder_request": {
                    "message": message,
                    "responder_request_targets": [
                        {"responder": _pagerduty_reference(item, "user_reference")} for item in responder_ids
                    ],
                }
            },
        )
        return {
            "provider": "pagerduty",
            "incident_id": incident_id,
            "status": "escalated",
            "responder_ids": responder_ids,
            "raw": data,
        }


class PagerDutyListOnCallTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        limit = _limit(context, params, default=20, maximum=100)
        schedule_id = _pagerduty_schedule_id(context, params)
        escalation_policy_id = _pagerduty_escalation_policy_id(context, params)
        query: dict[str, Any] = {"limit": limit}
        if schedule_id:
            query["schedule_ids[]"] = [schedule_id]
        if escalation_policy_id:
            query["escalation_policy_ids[]"] = [escalation_policy_id]
        data = await _http_json(
            "GET", f"{_pagerduty_base_url(context)}/oncalls", headers=_pagerduty_headers(context), params=query
        )
        rows = data.get("oncalls") or []
        return {
            "provider": "pagerduty",
            "count": len(rows),
            "oncalls": [
                {
                    "id": item.get("id"),
                    "user": (item.get("user") or {}).get("summary") or (item.get("user") or {}).get("id"),
                    "summary": item.get("summary"),
                    "schedule": (item.get("schedule") or {}).get("summary"),
                    "schedule_id": (item.get("schedule") or {}).get("id"),
                    "escalation_level": item.get("escalation_level"),
                    "start": item.get("start"),
                    "end": item.get("end"),
                }
                for item in rows[:limit]
            ],
        }


class PagerDutyAcknowledgeTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        incident_id = _string(params.get("incident_id") or params.get("alert_id"))
        if not incident_id:
            return {"error": "incident_id is required"}
        data = await _http_json(
            "PUT",
            f"{_pagerduty_base_url(context)}/incidents/{quote(incident_id, safe='')}",
            headers=_pagerduty_headers(context, include_from=_string(params.get("from_email")) or None),
            json_body={"incident": {"type": "incident_reference", "status": "acknowledged"}},
        )
        return {
            "provider": "pagerduty",
            "incident": _normalize_pagerduty_incident(data.get("incident") or {}),
            "raw": data,
        }


class PagerDutyResolveTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        incident_id = _string(params.get("incident_id") or params.get("alert_id"))
        if not incident_id:
            return {"error": "incident_id is required"}
        data = await _http_json(
            "PUT",
            f"{_pagerduty_base_url(context)}/incidents/{quote(incident_id, safe='')}",
            headers=_pagerduty_headers(context, include_from=_string(params.get("from_email")) or None),
            json_body={"incident": {"type": "incident_reference", "status": "resolved"}},
        )
        return {
            "provider": "pagerduty",
            "incident": _normalize_pagerduty_incident(data.get("incident") or {}),
            "raw": data,
        }


class PagerDutyGetScheduleTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        schedule_id = _pagerduty_schedule_id(context, params)
        if not schedule_id:
            return {"error": "schedule_id is required and must be allowed"}
        data = await _http_json(
            "GET",
            f"{_pagerduty_base_url(context)}/schedules/{quote(schedule_id, safe='')}",
            headers=_pagerduty_headers(context),
        )
        schedule = data.get("schedule") or {}
        return {
            "provider": "pagerduty",
            "schedule": {
                "id": schedule.get("id"),
                "name": schedule.get("name"),
                "time_zone": schedule.get("time_zone"),
                "description": schedule.get("description"),
                "html_url": schedule.get("html_url"),
            },
            "raw": data,
        }


class PagerDutyGetEscalationPolicyTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        escalation_policy_id = _pagerduty_escalation_policy_id(context, params)
        if not escalation_policy_id:
            return {"error": "escalation_policy_id is required and must be allowed"}
        data = await _http_json(
            "GET",
            f"{_pagerduty_base_url(context)}/escalation_policies/{quote(escalation_policy_id, safe='')}",
            headers=_pagerduty_headers(context),
        )
        policy = data.get("escalation_policy") or {}
        return {
            "provider": "pagerduty",
            "policy": {
                "id": policy.get("id"),
                "name": policy.get("name"),
                "description": policy.get("description"),
                "num_loops": policy.get("num_loops"),
                "services": [item.get("summary") or item.get("id") for item in (policy.get("services") or [])],
            },
            "raw": data,
        }
