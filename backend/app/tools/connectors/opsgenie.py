"""OpsGenie incident connector tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_OPSGENIE

from ..context import ToolContext
from .common import _limit, _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the opsgenie egress rule.
_http_json = connection_http_json(CONNECTION_OPSGENIE)


def _opsgenie_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("opsgenie_url") or "https://api.opsgenie.com").rstrip("/")


def _opsgenie_headers(context: ToolContext) -> dict[str, str]:
    token = _string(context.project_config.get("opsgenie_token"))
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"GenieKey {token}"
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


def _opsgenie_schedule_id(context: ToolContext, params: dict[str, Any]) -> str | None:
    return _resolve_allowed_identifier(
        params.get("schedule_id"), allowed=_normalize_string_list(context.project_config.get("opsgenie_schedule_ids"))
    )


def _opsgenie_team_id(context: ToolContext, params: dict[str, Any]) -> str | None:
    return _resolve_allowed_identifier(
        params.get("team_id"), allowed=_normalize_string_list(context.project_config.get("opsgenie_team_ids"))
    )


def _opsgenie_escalation_id(context: ToolContext, params: dict[str, Any]) -> str | None:
    return _resolve_allowed_identifier(
        params.get("escalation_policy_id") or params.get("escalation_id"),
        allowed=_normalize_string_list(context.project_config.get("opsgenie_escalation_ids")),
    )


def _normalize_opsgenie_alert(payload: dict[str, Any], *, request_id: str | None = None) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return {
        "request_id": request_id or payload.get("requestId") or payload.get("request_id"),
        "id": data.get("alertId") or data.get("id"),
        "alias": data.get("alias"),
        "tiny_id": data.get("tinyId"),
        "status": data.get("status"),
        "message": data.get("message") or payload.get("message"),
        "details": data.get("details") or {},
    }


class OpsGenieCreateIncidentTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        title = _string(params.get("title") or params.get("message"))
        if not title:
            return {"error": "title is required"}
        team_id = _opsgenie_team_id(context, params)
        payload = {
            "message": title,
            "description": _string(params.get("details") or params.get("description")) or title,
            "priority": _string(params.get("priority") or "").upper() or None,
            "tags": _normalize_string_list(params.get("tags")),
            "details": params.get("metadata") if isinstance(params.get("metadata"), dict) else {},
        }
        if team_id:
            payload["responders"] = [{"type": "team", "id": team_id}]
        data = await _http_json(
            "POST",
            f"{_opsgenie_base_url(context)}/v2/alerts",
            headers=_opsgenie_headers(context),
            json_body={key: value for key, value in payload.items() if value not in (None, "", [], {})},
        )
        return {"provider": "opsgenie", "incident": _normalize_opsgenie_alert(data), "raw": data}


class OpsGenieEscalateTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        incident_id = _string(params.get("incident_id") or params.get("alert_id"))
        if not incident_id:
            return {"error": "incident_id is required"}
        data = await _http_json(
            "POST",
            f"{_opsgenie_base_url(context)}/v2/alerts/{quote(incident_id, safe='')}/escalate",
            headers=_opsgenie_headers(context),
            params={"identifierType": _string(params.get("identifier_type") or "id")},
            json_body={"note": _string(params.get("message") or "Escalation requested by Octryx")},
        )
        return {"provider": "opsgenie", "incident_id": incident_id, "status": "escalated", "raw": data}


class OpsGenieListOnCallTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        schedule_id = _opsgenie_schedule_id(context, params)
        if not schedule_id:
            return {"error": "schedule_id is required and must be allowed"}
        limit = _limit(context, params, default=20, maximum=100)
        data = await _http_json(
            "GET",
            f"{_opsgenie_base_url(context)}/v2/schedules/{quote(schedule_id, safe='')}/on-calls",
            headers=_opsgenie_headers(context),
            params={"flat": "true"},
        )
        rows = ((data.get("data") or {}).get("onCallParticipants")) or []
        return {
            "provider": "opsgenie",
            "schedule_id": schedule_id,
            "count": len(rows),
            "oncalls": [
                {"name": item.get("name"), "id": item.get("id"), "type": item.get("type")} for item in rows[:limit]
            ],
        }


class OpsGenieAcknowledgeTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        incident_id = _string(params.get("incident_id") or params.get("alert_id"))
        if not incident_id:
            return {"error": "incident_id is required"}
        data = await _http_json(
            "POST",
            f"{_opsgenie_base_url(context)}/v2/alerts/{quote(incident_id, safe='')}/acknowledge",
            headers=_opsgenie_headers(context),
            params={"identifierType": _string(params.get("identifier_type") or "id")},
            json_body={"note": _string(params.get("message") or "Acknowledged by Octryx")},
        )
        return {
            "provider": "opsgenie",
            "incident": _normalize_opsgenie_alert(data, request_id=incident_id),
            "raw": data,
        }


class OpsGenieResolveTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        incident_id = _string(params.get("incident_id") or params.get("alert_id"))
        if not incident_id:
            return {"error": "incident_id is required"}
        data = await _http_json(
            "POST",
            f"{_opsgenie_base_url(context)}/v2/alerts/{quote(incident_id, safe='')}/close",
            headers=_opsgenie_headers(context),
            params={"identifierType": _string(params.get("identifier_type") or "id")},
            json_body={"note": _string(params.get("message") or "Resolved by Octryx")},
        )
        return {
            "provider": "opsgenie",
            "incident": _normalize_opsgenie_alert(data, request_id=incident_id),
            "raw": data,
        }


class OpsGenieGetScheduleTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        schedule_id = _opsgenie_schedule_id(context, params)
        if not schedule_id:
            return {"error": "schedule_id is required and must be allowed"}
        data = await _http_json(
            "GET",
            f"{_opsgenie_base_url(context)}/v2/schedules/{quote(schedule_id, safe='')}",
            headers=_opsgenie_headers(context),
            params={"identifierType": _string(params.get("identifier_type") or "id")},
        )
        schedule = data.get("data") or {}
        return {
            "provider": "opsgenie",
            "schedule": {
                "id": schedule.get("id"),
                "name": schedule.get("name"),
                "description": schedule.get("description"),
                "timezone": schedule.get("timezone"),
                "owner_team_id": ((schedule.get("ownerTeam") or {}).get("id")),
            },
            "raw": data,
        }


class OpsGenieGetEscalationPolicyTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        escalation_id = _opsgenie_escalation_id(context, params)
        if not escalation_id:
            return {"error": "escalation_policy_id is required and must be allowed"}
        data = await _http_json(
            "GET",
            f"{_opsgenie_base_url(context)}/v2/escalations/{quote(escalation_id, safe='')}",
            headers=_opsgenie_headers(context),
            params={"identifierType": _string(params.get("identifier_type") or "id")},
        )
        policy = data.get("data") or {}
        return {
            "provider": "opsgenie",
            "policy": {
                "id": policy.get("id"),
                "name": policy.get("name"),
                "description": policy.get("description"),
                "owner_team_id": ((policy.get("ownerTeam") or {}).get("id")),
            },
            "raw": data,
        }
