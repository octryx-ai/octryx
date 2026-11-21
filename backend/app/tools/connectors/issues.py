"""Issue connector tools spanning SonarQube and Linear."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from app.services.outbound_egress import CONNECTION_SONARQUBE

from ..context import ToolContext
from ..evidence_fields import item_url, with_source
from .common import _limit, _normalize_string_list, _string, connection_http_json
from .linear import _linear_graphql, _normalize_linear_issue, _resolve_linear_team, linear_issue_url
from .sonarqube import _resolve_sonarqube_project, _sonarqube_base_url, _sonarqube_headers

#: This module's HTTP helpers use the sonarqube egress rule.
_http_json = connection_http_json(CONNECTION_SONARQUBE)


def _issues_provider(context: ToolContext, params: dict[str, Any]) -> str:
    explicit = _string(params.get("provider") or context.project_config.get("issues_provider")).lower()
    if explicit in {"sonarqube", "linear"}:
        return explicit
    if _string(context.project_config.get("linear_api_key") or context.project_config.get("linear_url")):
        return "linear"
    if _string(context.project_config.get("sonarqube_url") or context.project_config.get("sonarqube_token")):
        return "sonarqube"
    return ""


class ListSonarQubeIssuesTool:
    name = "list_issues"
    description = "List SonarQube or Linear issues."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _issues_provider(context, params)
        if provider == "linear":
            team_id = _resolve_linear_team(context, params)
            if not team_id:
                return {"error": "team_id is required and must be allowed"}
            limit = _limit(context, params, default=20, maximum=100)
            query_text = _string(params.get("query"))
            state_id = _string(params.get("state_id"))
            data = await _linear_graphql(
                context,
                """
                query LinearIssues($teamId: String!, $first: Int!) {
                  team(id: $teamId) {
                    id
                    name
                    issues(first: $first) {
                      nodes {
                        id
                        identifier
                        url
                        title
                        description
                        priority
                        state { id name }
                        assignee { id name }
                      }
                    }
                  }
                }
                """,
                {"teamId": team_id, "first": limit},
            )
            team = data.get("team") or {}
            issues = [
                item
                for item in (team.get("issues") or {}).get("nodes") or []
                if (not query_text or query_text.lower() in json.dumps(item).lower())
                and (not state_id or _string((item.get("state") or {}).get("id")) == state_id)
            ]
            return {
                "provider": provider,
                "team_id": team_id,
                "team_name": team.get("name"),
                "count": len(issues[:limit]),
                # Each issue names its Linear page (evidence fields).
                "issues": [
                    with_source(
                        _normalize_linear_issue(item),
                        title=f"{item.get('identifier') or ''}: {item.get('title') or ''}",
                        url=linear_issue_url(context, item.get("url")),
                    )
                    for item in issues[:limit]
                ],
            }
        base = _sonarqube_base_url(context)
        project_key = _resolve_sonarqube_project(context, params)
        if not base:
            return {"error": "No SonarQube URL configured for this project"}
        if not project_key:
            return {"error": "project_key is required and must be allowed"}
        query: dict[str, Any] = {"componentKeys": project_key, "ps": _limit(context, params, default=20, maximum=100)}
        severities = _normalize_string_list(params.get("severities"))
        types = _normalize_string_list(params.get("types"))
        statuses = _normalize_string_list(params.get("statuses"))
        if severities:
            query["severities"] = ",".join(severities)
        if types:
            query["types"] = ",".join(types)
        if statuses:
            query["statuses"] = ",".join(statuses)
        data = await _http_json(
            "GET",
            f"{base}/api/issues/search",
            headers=_sonarqube_headers(context),
            params=query,
        )
        issues = data.get("issues") or []
        return {
            "provider": "sonarqube",
            "project_key": project_key,
            "count": len(issues),
            # Each issue names its page on the configured SonarQube (evidence fields).
            "issues": [
                with_source(
                    {
                        "key": item.get("key"),
                        "rule": item.get("rule"),
                        "severity": item.get("severity"),
                        "type": item.get("type"),
                        "status": item.get("status"),
                        "message": item.get("message"),
                        "component": item.get("component"),
                        "line": item.get("line"),
                    },
                    title=f"{project_key} {item.get('rule') or ''}: {item.get('message') or ''}",
                    url=item_url(base, "project", "issues", query=urlencode({"id": project_key, "open": item.get("key")}))
                    if item.get("key")
                    else None,
                )
                for item in issues
            ],
        }
