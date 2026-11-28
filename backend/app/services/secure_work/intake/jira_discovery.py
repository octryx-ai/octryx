"""What a Jira connection offers an intake: projects, issue types, statuses, fields and the live match count."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connector_auth.atlassian_modes import JIRA

from ....tools.jira_impl._jira_cloud import is_jira_cloud
from ...connector_auth.atlassian import auth_headers, request_auth
from ...outbound_egress.connections import CONNECTION_JIRA
from ..jira import jira_connector
from ..jira.jira_filters import build_jira_query_preview, normalize_jira_sync_filters
from ..jira.jira_mapping import suggested_state
from ..jira.jira_scope import parse_allowed_projects, restrict_jql, unsendable_query
from .connections import connection_config_of

APPROXIMATE_COUNT_PATH = "/rest/api/3/search/approximate-count"
SPRINT_SCHEMA = "com.pyxis.greenhopper.jira:gh-sprint"
# Field roles an intake maps, with the plain names Jira uses for them (the id is shown only as a hint).
FIELD_ROLES = (
    ("sprint_field", "Sprint", ("sprint",)),
    ("team_field", "Team", ("team",)),
    ("story_points_field", "Story points", ("story points", "story point estimate")),
    ("board_field", "Board", ("board",)),
)
REASON_NOT_CONFIGURED = "connection_not_configured"
REASON_UNAVAILABLE = "connection_unavailable"
REASON_QUERY = "query_refused"
REASON_FAILED = "jira_request_failed"


class _Jira:
    def __init__(self, config: dict[str, Any]) -> None:
        self.url = str(config.get("jira_url") or "").strip().rstrip("/")
        self.headers = {"Accept": "application/json", **auth_headers(JIRA, config)}
        self.auth = request_auth(JIRA, config)
        self.cloud = bool(self.url) and is_jira_cloud(self.url, config)
        self.ready = bool(self.url) and (len(self.headers) > 1 or self.auth is not None)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=20, follow_redirects=True, auth=self.auth,
                                 transport=jira_connector.egress_transport(CONNECTION_JIRA))

    async def get(self, client: httpx.AsyncClient, path: str, params: dict | None = None) -> Any:
        payload, _version = await jira_connector._jira_api_get(client, self.url, path, headers=self.headers,
                                                               params=params)
        return payload


async def _config(db: AsyncSession, project_id: str, connection_id: str) -> tuple[dict[str, Any] | None, str | None]:
    config = await connection_config_of(db, project_id, "jira", connection_id)
    if config is None:
        return None, REASON_UNAVAILABLE
    return config, None


def _field_roles(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roles = []
    for role, label, names in FIELD_ROLES:
        found = None
        for field in fields:
            name = str(field.get("name") or "").strip()
            schema = field.get("schema") if isinstance(field.get("schema"), dict) else {}
            custom = str(schema.get("custom") or "")
            if (role == "sprint_field" and custom == SPRINT_SCHEMA) or name.lower() in names or (
                    role == "team_field" and "atlassian-team" in custom):
                found = {"id": str(field.get("id") or ""), "name": name}
                break
        roles.append({"role": role, "label": label, "field": found})
    return roles


async def discover_jira(db: AsyncSession, project_id: str, connection_id: str) -> dict[str, Any]:
    empty: dict[str, Any] = {"projects": [], "issue_types": [], "statuses": [], "fields": _field_roles([]),
                             "reason": None}
    config, reason = await _config(db, project_id, connection_id)
    if config is None:
        return {**empty, "reason": reason}
    allowed = parse_allowed_projects(config.get("jira_allowed_projects"))
    jira = _Jira(config)
    if not jira.ready:
        projects = [{"key": key, "name": key} for key in sorted(allowed or ())]
        return {**empty, "projects": projects, "reason": REASON_NOT_CONFIGURED}
    result = dict(empty)
    async with jira.client() as client:
        try:
            listed = await jira.get(client, "/project")
            projects = [{"key": str(entry.get("key") or "").upper(), "name": str(entry.get("name") or entry.get("key"))}
                        for entry in listed if isinstance(entry, dict) and entry.get("key")]
            result["projects"] = [entry for entry in projects if allowed is None or entry["key"] in allowed]
            if allowed is not None:  # a bound project Jira did not list is still offered by its key
                listed_keys = {entry["key"] for entry in result["projects"]}
                result["projects"] += [{"key": key, "name": key} for key in sorted(allowed - listed_keys)]
            types = await jira.get(client, "/issuetype")
            result["issue_types"] = sorted({
                str(entry.get("name")) for entry in types
                if isinstance(entry, dict) and entry.get("name") and not entry.get("subtask")})
            statuses: dict[str, dict[str, Any]] = {}
            for entry in await jira.get(client, "/status"):
                if not isinstance(entry, dict) or not entry.get("name"):
                    continue
                category = str((entry.get("statusCategory") or {}).get("key") or "") or None
                statuses.setdefault(str(entry["name"]), {"name": str(entry["name"]), "category": category,
                                                         "state": suggested_state(str(entry["name"]), category)})
            result["statuses"] = sorted(statuses.values(), key=lambda entry: entry["name"].lower())
            fields = await jira.get(client, "/field")
            result["fields"] = _field_roles([entry for entry in fields if isinstance(entry, dict)])
        except (httpx.HTTPError, ValueError, TypeError):
            result["reason"] = REASON_FAILED
            if not result["projects"]:
                result["projects"] = [{"key": key, "name": key} for key in sorted(allowed or ())]
    return result


async def count_jira(db: AsyncSession, project_id: str, connection_id: str, what: dict[str, Any]) -> dict[str, Any]:
    config, reason = await _config(db, project_id, connection_id)
    if config is None:
        return {"count": None, "reason": reason}
    jira = _Jira(config)
    if not jira.ready:
        return {"count": None, "reason": REASON_NOT_CONFIGURED}
    allowed = parse_allowed_projects(config.get("jira_allowed_projects"))
    filters = normalize_jira_sync_filters(what)
    outside = {key.upper() for key in filters.get("project_keys") or []} - set(allowed or ())
    query = build_jira_query_preview(filters)
    if (allowed is not None and outside) or unsendable_query(query) is not None:
        return {"count": None, "reason": REASON_QUERY}
    try:
        query = restrict_jql(query, allowed)
    except Exception:  # noqa: BLE001 - an allowlist without a usable key admits nothing
        return {"count": None, "reason": REASON_QUERY}
    body_query = query.split(" ORDER BY ")[0]
    async with jira.client() as client:
        try:
            if jira.cloud:
                response = await client.post(f"{jira.url}{APPROXIMATE_COUNT_PATH}", json={"jql": body_query},
                                             headers={**jira.headers, "Content-Type": "application/json"})
                response.raise_for_status()
                count = response.json().get("count")
            else:
                payload = await jira.get(client, "/search", {"jql": body_query, "maxResults": 0, "fields": "key"})
                count = payload.get("total")
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return {"count": None, "reason": REASON_FAILED}
    return {"count": count if type(count) is int else None, "reason": None, "query": query}


__all__ = ["FIELD_ROLES", "count_jira", "discover_jira"]
