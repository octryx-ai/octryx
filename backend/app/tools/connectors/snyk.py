"""Snyk connector tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_SNYK

from ..context import ToolContext
from .common import _limit, _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the snyk egress rule.
_http_json = connection_http_json(CONNECTION_SNYK)


def _snyk_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("snyk_url") or "https://api.snyk.io").rstrip("/")


def _snyk_headers(context: ToolContext) -> dict[str, str]:
    token = _string(context.project_config.get("snyk_token"))
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _snyk_org_id(context: ToolContext) -> str:
    return _string(context.project_config.get("snyk_org_id"))


def _resolve_snyk_project(context: ToolContext, params: dict[str, Any]) -> str | None:
    project_id = _string(params.get("project_id") or params.get("project"))
    allowed = _normalize_string_list(context.project_config.get("snyk_allowed_projects"))
    if not project_id and len(allowed) == 1:
        project_id = allowed[0]
    if not project_id:
        return None
    if allowed and project_id not in allowed:
        return None
    return project_id


class ListSnykVulnerabilitiesTool:
    name = "list_vulnerabilities"
    description = "List Snyk vulnerabilities for an allowed project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _snyk_base_url(context)
        org_id = _snyk_org_id(context)
        project_id = _resolve_snyk_project(context, params)
        if not base:
            return {"error": "No Snyk URL configured for this project"}
        if not org_id:
            return {"error": "snyk_org_id is required"}
        if not project_id:
            return {"error": "project_id is required and must be allowed"}
        data = await _http_json(
            "GET",
            f"{base}/v1/org/{quote(org_id, safe='')}/project/{quote(project_id, safe='')}/issues",
            headers=_snyk_headers(context),
        )
        vulnerabilities = ((data.get("issues") or {}).get("vulnerabilities")) or []
        return {
            "project_id": project_id,
            "count": len(vulnerabilities),
            "vulnerabilities": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "severity": item.get("severity"),
                    "package_name": item.get("packageName"),
                    "version": item.get("version"),
                    "identifiers": item.get("identifiers") or {},
                }
                for item in vulnerabilities[: _limit(context, params, default=50, maximum=200)]
            ],
        }


class GetSnykSeverityTool:
    name = "get_severity"
    description = "Get severity details for a Snyk issue."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        vulnerabilities = await ListSnykVulnerabilitiesTool().execute(params, context)
        if vulnerabilities.get("error"):
            return vulnerabilities
        issue_id = _string(params.get("issue_id"))
        if not issue_id:
            return {"error": "issue_id is required"}
        for item in vulnerabilities.get("vulnerabilities") or []:
            if _string(item.get("id")) == issue_id:
                return {
                    "issue_id": issue_id,
                    "project_id": vulnerabilities.get("project_id"),
                    "severity": item.get("severity"),
                    "package_name": item.get("package_name"),
                    "title": item.get("title"),
                }
        return {"error": "issue_id was not found in the allowed project scope"}


class GetSnykFixAdviceTool:
    name = "get_fix_advice"
    description = "Get fix advice for a Snyk issue in an allowed project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _snyk_base_url(context)
        org_id = _snyk_org_id(context)
        project_id = _resolve_snyk_project(context, params)
        issue_id = _string(params.get("issue_id"))
        if not base:
            return {"error": "No Snyk URL configured for this project"}
        if not org_id:
            return {"error": "snyk_org_id is required"}
        if not project_id:
            return {"error": "project_id is required and must be allowed"}
        if not issue_id:
            return {"error": "issue_id is required"}
        data = await _http_json(
            "GET",
            f"{base}/v1/org/{quote(org_id, safe='')}/project/{quote(project_id, safe='')}/issue/{quote(issue_id, safe='')}",
            headers=_snyk_headers(context),
        )
        issue = data.get("issue") or data
        return {
            "issue_id": issue_id,
            "project_id": project_id,
            "title": issue.get("title"),
            "severity": issue.get("severity"),
            "fix_advice": issue.get("fixAdvice") or issue.get("fixedIn") or [],
            "upgrade_path": issue.get("upgradePath") or [],
        }
