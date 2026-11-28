"""Grafana tool implementations."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_GRAFANA, egress_transport

from .context import ToolContext
from .evidence_fields import item_url, with_source


def _alert_rule_url(grafana_url: object, uid: object) -> str | None:
    return item_url(str(grafana_url or "").rstrip("/"), "alerting", "grafana", uid, "view")


def _with_rule_source(rule: object, grafana_url: object) -> object:
    if not isinstance(rule, dict):
        return rule
    url = _alert_rule_url(grafana_url, rule.get("uid"))
    return with_source(rule, title=rule.get("title") or rule.get("uid"), url=url)


class ReadGrafanaAlert:
    name = "read_grafana_alert"
    description = "Read details of a specific Grafana alert by ID"

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        grafana_url = context.project_config.get("grafana_url")
        grafana_token = context.project_config.get("grafana_token")

        if not grafana_url:
            return {"error": "No Grafana URL configured for this project"}

        alert_id = params["alert_id"]

        async with httpx.AsyncClient(timeout=30, transport=egress_transport(CONNECTION_GRAFANA)) as client:
            headers = {"Authorization": f"Bearer {grafana_token}"} if grafana_token else {}

            # Get alert rule
            resp = await client.get(
                f"{grafana_url}/api/v1/provisioning/alert-rules/{alert_id}",
                headers=headers,
            )
            if resp.status_code != 200:
                # Try unified alerting API
                resp = await client.get(
                    f"{grafana_url}/api/alertmanager/grafana/api/v2/alerts",
                    headers=headers,
                )

            resp.raise_for_status()
            data = resp.json()

        # The alert rule's view page on the configured Grafana (evidence fields).
        return with_source(
            {"alert_id": alert_id, "grafana_url": grafana_url, "data": data},
            title=(data.get("title") if isinstance(data, dict) else None) or f"Grafana alert rule {alert_id}",
            url=_alert_rule_url(grafana_url, alert_id),
        )


class ListGrafanaAlerts:
    name = "list_grafana_alerts"
    description = "List all active Grafana alerts"

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        grafana_url = context.project_config.get("grafana_url")
        grafana_token = context.project_config.get("grafana_token")

        if not grafana_url:
            return {"error": "No Grafana URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=egress_transport(CONNECTION_GRAFANA)) as client:
            headers = {"Authorization": f"Bearer {grafana_token}"} if grafana_token else {}

            # Get alert rules
            resp = await client.get(
                f"{grafana_url}/api/v1/provisioning/alert-rules",
                headers=headers,
            )
            resp.raise_for_status()
            rules = resp.json()

            # Get active alerts
            resp2 = await client.get(
                f"{grafana_url}/api/alertmanager/grafana/api/v2/alerts",
                headers=headers,
            )
            active_alerts = resp2.json() if resp2.status_code == 200 else []

        return {
            "total_rules": len(rules),
            "active_alerts": len(active_alerts),
            # Each alert rule names its view page on the configured Grafana (evidence fields).
            "rules": [_with_rule_source(rule, grafana_url) for rule in rules] if isinstance(rules, list) else rules,
            "active": active_alerts,
        }


def _grafana_headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class RenderGrafanaPanelAsImage:
    name = "render_panel_as_image"
    description = "Render a Grafana panel as an image."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        grafana_url = str(context.project_config.get("grafana_url") or "").rstrip("/")
        grafana_token = context.project_config.get("grafana_token")
        dashboard_uid = str(params.get("dashboard_uid") or "").strip()
        panel_id = params.get("panel_id")
        if not grafana_url:
            return {"error": "No Grafana URL configured for this project"}
        if not dashboard_uid:
            return {"error": "dashboard_uid is required"}
        if panel_id is None:
            return {"error": "panel_id is required"}
        query = {
            "panelId": panel_id,
            "from": params.get("from") or "now-6h",
            "to": params.get("to") or "now",
            "theme": params.get("theme") or "dark",
            "width": params.get("width") or 1600,
            "height": params.get("height") or 900,
        }
        render_url = f"{grafana_url}/render/d-solo/{dashboard_uid}"
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GRAFANA)
        ) as client:
            resp = await client.get(render_url, headers=_grafana_headers(grafana_token), params=query)
        resp.raise_for_status()
        # The panel's view on the configured Grafana dashboard (evidence fields).
        return with_source(
            {
                "dashboard_uid": dashboard_uid,
                "panel_id": panel_id,
                "render_url": str(resp.request.url),
                "content_type": resp.headers.get("content-type"),
                "bytes": len(resp.content or b""),
            },
            title=f"Grafana dashboard {dashboard_uid} panel {panel_id}",
            url=item_url(grafana_url, "d", dashboard_uid, query=f"viewPanel={panel_id}"),
        )


class CreateGrafanaSnapshot:
    name = "create_snapshot"
    description = "Create a Grafana snapshot for a dashboard."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        grafana_url = str(context.project_config.get("grafana_url") or "").rstrip("/")
        grafana_token = context.project_config.get("grafana_token")
        dashboard = params.get("dashboard")
        dashboard_uid = str(params.get("dashboard_uid") or "").strip()
        if not grafana_url:
            return {"error": "No Grafana URL configured for this project"}
        if dashboard is None and not dashboard_uid:
            return {"error": "dashboard_uid or dashboard is required"}
        if dashboard is None:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GRAFANA)
            ) as client:
                dash_resp = await client.get(
                    f"{grafana_url}/api/dashboards/uid/{dashboard_uid}",
                    headers=_grafana_headers(grafana_token),
                )
            dash_resp.raise_for_status()
            dashboard = dash_resp.json().get("dashboard") or {}
        payload = {
            "dashboard": dashboard,
            "name": params.get("name") or (dashboard.get("title") if isinstance(dashboard, dict) else "Snapshot"),
            "expires": params.get("expires") or 3600,
        }
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GRAFANA)
        ) as client:
            resp = await client.post(
                f"{grafana_url}/api/snapshots",
                headers={**_grafana_headers(grafana_token), "Content-Type": "application/json"},
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        return {
            "snapshot_url": data.get("url"),
            "delete_url": data.get("deleteUrl"),
            "key": data.get("key"),
            "name": payload["name"],
        }


class GetGrafanaDashboardJson:
    name = "get_dashboard_json"
    description = "Get the full Grafana dashboard JSON by UID."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        grafana_url = str(context.project_config.get("grafana_url") or "").rstrip("/")
        grafana_token = context.project_config.get("grafana_token")
        dashboard_uid = str(params.get("dashboard_uid") or "").strip()
        if not grafana_url:
            return {"error": "No Grafana URL configured for this project"}
        if not dashboard_uid:
            return {"error": "dashboard_uid is required"}
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GRAFANA)
        ) as client:
            resp = await client.get(
                f"{grafana_url}/api/dashboards/uid/{dashboard_uid}",
                headers=_grafana_headers(grafana_token),
            )
        resp.raise_for_status()
        payload = resp.json()
        dashboard = payload.get("dashboard") or {}
        meta = payload.get("meta") or {}
        # The dashboard's page on the configured Grafana (evidence fields).
        return with_source(
            {
                "dashboard_uid": dashboard_uid,
                "title": dashboard.get("title"),
                "version": dashboard.get("version"),
                "meta": meta,
                "dashboard": dashboard,
            },
            title=dashboard.get("title") or dashboard_uid,
            url=item_url(grafana_url, "d", dashboard_uid),
        )
