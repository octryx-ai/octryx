"""Incident tools that dispatch to the configured provider (PagerDuty, OpsGenie, Statuspage)."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .common import _string
from .opsgenie import (
    OpsGenieAcknowledgeTool,
    OpsGenieCreateIncidentTool,
    OpsGenieEscalateTool,
    OpsGenieGetEscalationPolicyTool,
    OpsGenieGetScheduleTool,
    OpsGenieListOnCallTool,
    OpsGenieResolveTool,
)
from .pagerduty import (
    PagerDutyAcknowledgeTool,
    PagerDutyCreateIncidentTool,
    PagerDutyEscalateTool,
    PagerDutyGetEscalationPolicyTool,
    PagerDutyGetScheduleTool,
    PagerDutyListOnCallTool,
    PagerDutyResolveTool,
)
from .statuspage import (
    StatuspageCreateIncidentTool,
)


def _incident_provider(context: ToolContext, params: dict[str, Any]) -> str:
    explicit = _string(params.get("provider") or context.project_config.get("incident_provider")).lower()
    if explicit in {"pagerduty", "opsgenie", "statuspage"}:
        return explicit
    if _string(
        context.project_config.get("statuspage_api_key")
        or context.project_config.get("statuspage_page_id")
        or context.project_config.get("statuspage_url")
    ):
        return "statuspage"
    if _string(context.project_config.get("opsgenie_token") or context.project_config.get("opsgenie_url")):
        return "opsgenie"
    if _string(context.project_config.get("pagerduty_token") or context.project_config.get("pagerduty_url")):
        return "pagerduty"
    return ""


class CreateIncidentTool:
    name = "create_incident"
    description = "Create an incident/alert in PagerDuty, OpsGenie or Statuspage."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _incident_provider(context, params)
        title = _string(params.get("title") or params.get("message"))
        if not provider:
            return {"error": "No PagerDuty, OpsGenie or Statuspage connector is configured for this project"}
        if not title:
            return {"error": "title is required"}
        if provider == "statuspage":
            return await StatuspageCreateIncidentTool().execute(params, context)
        if provider == "pagerduty":
            return await PagerDutyCreateIncidentTool().execute(params, context)
        return await OpsGenieCreateIncidentTool().execute(params, context)


class EscalateTool:
    name = "escalate"
    description = "Escalate an existing PagerDuty incident or OpsGenie alert."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _incident_provider(context, params)
        incident_id = _string(params.get("incident_id") or params.get("alert_id"))
        if not provider:
            return {"error": "No PagerDuty or OpsGenie connector is configured for this project"}
        if not incident_id:
            return {"error": "incident_id is required"}
        if provider == "pagerduty":
            return await PagerDutyEscalateTool().execute(params, context)
        return await OpsGenieEscalateTool().execute(params, context)


class ListOnCallTool:
    name = "list_oncall"
    description = "List current on-call responders from PagerDuty or OpsGenie."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _incident_provider(context, params)
        if not provider:
            return {"error": "No PagerDuty or OpsGenie connector is configured for this project"}
        if provider == "pagerduty":
            return await PagerDutyListOnCallTool().execute(params, context)
        return await OpsGenieListOnCallTool().execute(params, context)


class AcknowledgeTool:
    name = "acknowledge"
    description = "Acknowledge a PagerDuty incident or OpsGenie alert."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _incident_provider(context, params)
        incident_id = _string(params.get("incident_id") or params.get("alert_id"))
        if not provider:
            return {"error": "No PagerDuty or OpsGenie connector is configured for this project"}
        if not incident_id:
            return {"error": "incident_id is required"}
        if provider == "pagerduty":
            return await PagerDutyAcknowledgeTool().execute(params, context)
        return await OpsGenieAcknowledgeTool().execute(params, context)


class ResolveTool:
    name = "resolve"
    description = "Resolve a PagerDuty incident or OpsGenie alert."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _incident_provider(context, params)
        incident_id = _string(params.get("incident_id") or params.get("alert_id"))
        if not provider:
            return {"error": "No PagerDuty or OpsGenie connector is configured for this project"}
        if not incident_id:
            return {"error": "incident_id is required"}
        if provider == "pagerduty":
            return await PagerDutyResolveTool().execute(params, context)
        return await OpsGenieResolveTool().execute(params, context)


class GetScheduleTool:
    name = "get_schedule"
    description = "Get schedule metadata from PagerDuty or OpsGenie."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _incident_provider(context, params)
        if not provider:
            return {"error": "No PagerDuty or OpsGenie connector is configured for this project"}
        if provider == "pagerduty":
            return await PagerDutyGetScheduleTool().execute(params, context)
        return await OpsGenieGetScheduleTool().execute(params, context)


class GetEscalationPolicyTool:
    name = "get_escalation_policy"
    description = "Get escalation policy metadata from PagerDuty or OpsGenie."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _incident_provider(context, params)
        if not provider:
            return {"error": "No PagerDuty or OpsGenie connector is configured for this project"}
        if provider == "pagerduty":
            return await PagerDutyGetEscalationPolicyTool().execute(params, context)
        return await OpsGenieGetEscalationPolicyTool().execute(params, context)
