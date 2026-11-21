"""SonarQube connector tools."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlencode

from app.services.outbound_egress import CONNECTION_SONARQUBE

from ..context import ToolContext
from ..evidence_fields import item_url, with_source
from .common import _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the sonarqube egress rule.
_http_json = connection_http_json(CONNECTION_SONARQUBE)


def _sonarqube_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("sonarqube_url")).rstrip("/")


def _sonarqube_headers(context: ToolContext) -> dict[str, str]:
    token = _string(context.project_config.get("sonarqube_token"))
    headers = {"Accept": "application/json"}
    if token:
        auth = base64.b64encode(f"{token}:".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {auth}"
    return headers


def _sonarqube_allowed_projects(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("sonarqube_allowed_projects"))


def with_dashboard_source(result: dict[str, Any], base: str, project_key: str) -> dict[str, Any]:
    """The project's dashboard on the configured SonarQube: ``{base}/dashboard?id={project}``."""
    url = item_url(base, "dashboard", query=urlencode({"id": project_key})) if project_key else None
    return with_source(result, title=f"SonarQube {project_key}", url=url)


def _resolve_sonarqube_project(context: ToolContext, params: dict[str, Any]) -> str | None:
    project_key = _string(params.get("project_key") or params.get("project"))
    allowed = _sonarqube_allowed_projects(context)
    if not project_key and len(allowed) == 1:
        project_key = allowed[0]
    if not project_key:
        return None
    if allowed and project_key not in allowed:
        return None
    return project_key


class GetSonarQubeProjectMetricsTool:
    name = "get_project_metrics"
    description = "Get SonarQube project metrics for an allowed project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _sonarqube_base_url(context)
        project_key = _resolve_sonarqube_project(context, params)
        if not base:
            return {"error": "No SonarQube URL configured for this project"}
        if not project_key:
            return {"error": "project_key is required and must be allowed"}
        requested = _normalize_string_list(params.get("metrics")) or [
            "bugs",
            "vulnerabilities",
            "code_smells",
            "coverage",
            "duplicated_lines_density",
        ]
        data = await _http_json(
            "GET",
            f"{base}/api/measures/component",
            headers=_sonarqube_headers(context),
            params={"component": project_key, "metricKeys": ",".join(requested)},
        )
        component = data.get("component") or {}
        measures = component.get("measures") or []
        metrics = {item.get("metric"): item.get("value") for item in measures if item.get("metric")}
        result = {"project_key": project_key, "metrics": metrics, "requested_metrics": requested}
        return with_dashboard_source(result, base, project_key)


class GetSonarQubeQualityGateTool:
    name = "get_quality_gate"
    description = "Get the SonarQube quality gate status for an allowed project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _sonarqube_base_url(context)
        project_key = _resolve_sonarqube_project(context, params)
        if not base:
            return {"error": "No SonarQube URL configured for this project"}
        if not project_key:
            return {"error": "project_key is required and must be allowed"}
        data = await _http_json(
            "GET",
            f"{base}/api/qualitygates/project_status",
            headers=_sonarqube_headers(context),
            params={"projectKey": project_key},
        )
        status = data.get("projectStatus") or {}
        result = {
            "project_key": project_key,
            "status": status.get("status"),
            "conditions": status.get("conditions") or [],
            "ignored_conditions": status.get("ignoredConditions"),
        }
        return with_dashboard_source(result, base, project_key)
