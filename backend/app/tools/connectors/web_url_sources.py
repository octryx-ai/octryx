"""Source links for connector reads whose web host is configured, not guessed."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...services.tool_config.web_url import OPSGENIE_WEB_URL_FIELD, WEB_URL_FIELDS
from ..evidence_fields import http_url, item_url, with_source
from .web_url_cloud_sources import CLOUD_WEB_URL_LINKERS
from .web_url_linking import Linker, _items, _one, _query, _web

# --- Datadog, New Relic, Snyk ---------------------------------------------------------------------------


def _datadog_monitors(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    base = _web(config, WEB_URL_FIELDS["datadog"])
    return _items(result, "monitors", lambda item: with_source(
        item, title=f"Datadog monitor {item.get('name') or item.get('id')}",
        url=item_url(base, "monitors", item.get("id")) if base else None,
    ))


def _datadog_events(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    base = _web(config, WEB_URL_FIELDS["datadog"])
    return _items(result, "events", lambda item: with_source(
        item, title=f"Datadog event {item.get('title') or item.get('id')}",
        url=item_url(base, "event", "event", query=_query(id=item.get("id"))) if base and item.get("id") else None,
    ))


def _newrelic_alerts(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    base = _web(config, WEB_URL_FIELDS["newrelic"])
    account = str(config.get("newrelic_account_id") or "").strip()
    if result.get("provider") != "newrelic" or not base or not account:
        return result
    return _items(result, "alerts", lambda item: with_source(
        item, title=f"New Relic incident {item.get('label') or item.get('incident_id')}",
        url=item_url(base, "accounts", account, "incidents", item.get("incident_id")),
    ))


def _snyk_issue(base: str | None, project_id: object, issue_id: object) -> str | None:
    if not base or not str(issue_id or "").strip():
        return None
    return item_url(base, "project", project_id, fragment=f"issue-{quote(str(issue_id), safe='')}")


def _snyk_vulnerabilities(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    base = _web(config, WEB_URL_FIELDS["snyk"])
    project_id = result.get("project_id")
    return _items(result, "vulnerabilities", lambda item: with_source(
        item, title=f"Snyk {item.get('title') or item.get('id')}", url=_snyk_issue(base, project_id, item.get("id"))
    ))


def _snyk_issue_result(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    base = _web(config, WEB_URL_FIELDS["snyk"])
    url = _snyk_issue(base, result.get("project_id"), result.get("issue_id"))
    return with_source(result, title=f"Snyk {result.get('title') or result.get('issue_id')}", url=url)


# --- PagerDuty / Opsgenie, Statuspage -------------------------------------------------------------------

_INCIDENT_PAGES = {
    "pagerduty": {"schedule": ("schedules",), "policy": ("escalation_policies",)},
    "opsgenie": {"schedule": ("settings", "schedule", "detail"), "policy": ("settings", "escalation", "detail")},
}


def _incident_base(result: dict[str, Any], config: dict[str, Any]) -> tuple[str, str | None]:
    provider = str(result.get("provider") or "")
    field = WEB_URL_FIELDS["pagerduty"] if provider == "pagerduty" else OPSGENIE_WEB_URL_FIELD
    return provider, _web(config, field) if provider in _INCIDENT_PAGES else None


def _incident_page(provider: str, base: str | None, kind: str, item_id: object) -> str | None:
    return item_url(base, *_INCIDENT_PAGES[provider][kind], item_id) if base else None


def _incident_schedule(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    provider, base = _incident_base(result, config)
    if base is None:
        return result
    return _one(result, "schedule", lambda item: with_source(
        item, title=f"{provider} schedule {item.get('name') or item.get('id')}",
        url=_incident_page(provider, base, "schedule", item.get("id")),
    ))


def _incident_policy(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    provider, base = _incident_base(result, config)
    if base is None:
        return result
    return _one(result, "policy", lambda item: with_source(
        item, title=f"{provider} escalation policy {item.get('name') or item.get('id')}",
        url=_incident_page(provider, base, "policy", item.get("id")),
    ))


def _incident_oncall(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    provider, base = _incident_base(result, config)
    if base is None:
        return result
    if provider == "opsgenie":
        url = _incident_page(provider, base, "schedule", result.get("schedule_id"))
        return with_source(result, title=f"opsgenie on-call {result.get('schedule_id')}", url=url)
    return _items(result, "oncalls", lambda item: with_source(
        item, title=f"pagerduty on-call {item.get('schedule') or item.get('schedule_id')}",
        url=_incident_page(provider, base, "schedule", item.get("schedule_id")),
    ))


def _statuspage_components(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    page = http_url(_web(config, WEB_URL_FIELDS["statuspage"]))
    # The public page shows every component; a component has no page of its own.
    return _items(result, "components", lambda item: with_source(
        item, title=f"Status page: {item.get('name') or item.get('id')}", url=page
    ))


WEB_URL_LINKERS: dict[str, Linker] = {
    "list_monitors": _datadog_monitors,
    "get_events": _datadog_events,
    "get_alerts": _newrelic_alerts,
    "list_vulnerabilities": _snyk_vulnerabilities,
    "get_severity": _snyk_issue_result,
    "get_fix_advice": _snyk_issue_result,
    "get_schedule": _incident_schedule,
    "get_escalation_policy": _incident_policy,
    "list_oncall": _incident_oncall,
    "list_components": _statuspage_components,
    **CLOUD_WEB_URL_LINKERS,
}


def link_configured_web_sources(tool_name: str, result: Any, project_config: dict[str, Any] | None) -> Any:
    linker = WEB_URL_LINKERS.get(tool_name)
    if linker is None or not isinstance(result, dict) or result.get("error"):
        return result
    return linker(result, dict(project_config or {}))


__all__ = ["WEB_URL_LINKERS", "link_configured_web_sources"]
