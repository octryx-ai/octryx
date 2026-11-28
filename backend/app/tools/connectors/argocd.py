"""ArgoCD connector tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_ARGOCD

from ..context import ToolContext
from ..evidence_fields import item_url, with_source
from .common import _headers_with_bearer, _limit, _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the argocd egress rule.
_http_json = connection_http_json(CONNECTION_ARGOCD)


def _argocd_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("argocd_url")).rstrip("/")


def _argocd_headers(context: ToolContext) -> dict[str, str]:
    token = _string(context.project_config.get("argocd_token"))
    return _headers_with_bearer(token or None, extra={"Accept": "application/json"})


def _argocd_allowed_applications(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("argocd_allowed_applications"))


def _resolve_argocd_application(context: ToolContext, params: dict[str, Any]) -> str | None:
    app_name = _string(params.get("app_name") or params.get("application"))
    allowed = _argocd_allowed_applications(context)
    if not app_name and len(allowed) == 1:
        app_name = allowed[0]
    if not app_name:
        return None
    if allowed and app_name not in allowed:
        return None
    return app_name


def with_application_source(item: dict[str, Any], base: str, app_name: Any) -> dict[str, Any]:
    return with_source(item, title=f"ArgoCD {app_name}", url=item_url(base, "applications", app_name))


def _normalize_argocd_application(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    operation_state = status.get("operationState") or {}
    sync = status.get("sync") or {}
    health = status.get("health") or {}
    history = status.get("history") or []
    return {
        "name": metadata.get("name"),
        "project": spec.get("project"),
        "repo_url": (spec.get("source") or {}).get("repoURL"),
        "target_revision": (spec.get("source") or {}).get("targetRevision"),
        "path": (spec.get("source") or {}).get("path"),
        "sync_status": sync.get("status"),
        "health_status": health.get("status"),
        "operation_phase": operation_state.get("phase"),
        "revision": sync.get("revision"),
        "history_count": len(history),
    }


class ListArgoCdAppsTool:
    name = "list_apps"
    description = "List ArgoCD applications visible to the configured connector."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _argocd_base_url(context)
        if not base:
            return {"error": "No ArgoCD URL configured for this project"}
        allowed = _argocd_allowed_applications(context)
        limit = _limit(context, params, default=20, maximum=100)
        data = await _http_json("GET", f"{base}/api/v1/applications", headers=_argocd_headers(context))
        items = data.get("items") or []
        if allowed:
            items = [item for item in items if _string((item.get("metadata") or {}).get("name")) in allowed]
        return {
            "count": len(items[:limit]),
            # Each application names its page on the configured ArgoCD (evidence fields).
            "applications": [
                with_application_source(app, base, app.get("name"))
                for app in (_normalize_argocd_application(item) for item in items[:limit])
            ],
        }


class GetArgoCdAppStatusTool:
    name = "get_app_status"
    description = "Get status of a single ArgoCD application."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _argocd_base_url(context)
        app_name = _resolve_argocd_application(context, params)
        if not base:
            return {"error": "No ArgoCD URL configured for this project"}
        if not app_name:
            return {"error": "app_name is required and must be allowed"}
        data = await _http_json(
            "GET", f"{base}/api/v1/applications/{quote(app_name, safe='')}", headers=_argocd_headers(context)
        )
        return {"application": with_application_source(_normalize_argocd_application(data), base, app_name)}


class SyncArgoCdAppTool:
    name = "sync_app"
    description = "Trigger a sync for a single ArgoCD application."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _argocd_base_url(context)
        app_name = _resolve_argocd_application(context, params)
        if not base:
            return {"error": "No ArgoCD URL configured for this project"}
        if not app_name:
            return {"error": "app_name is required and must be allowed"}
        payload: dict[str, Any] = {}
        revision = _string(params.get("revision"))
        if revision:
            payload["revision"] = revision
        if "prune" in params:
            payload["prune"] = bool(params.get("prune"))
        if "dry_run" in params:
            payload["dryRun"] = bool(params.get("dry_run"))
        data = await _http_json(
            "POST",
            f"{base}/api/v1/applications/{quote(app_name, safe='')}/sync",
            headers=_argocd_headers(context),
            json_body=payload or {},
        )
        return {"app_name": app_name, "status": "sync_started", "operation": data}


class GetArgoCdRolloutStatusTool:
    name = "get_rollout_status"
    description = "Inspect rollout and operation state for a single ArgoCD application."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        app_name = _resolve_argocd_application(context, params)
        if not app_name:
            return {"error": "app_name is required and must be allowed"}
        data = await _http_json(
            "GET",
            f"{_argocd_base_url(context)}/api/v1/applications/{quote(app_name, safe='')}",
            headers=_argocd_headers(context),
        )
        status = data.get("status") or {}
        operation = status.get("operationState") or {}
        return with_application_source({
            "app_name": app_name,
            "sync_status": (status.get("sync") or {}).get("status"),
            "health_status": (status.get("health") or {}).get("status"),
            "operation_phase": operation.get("phase"),
            "operation_message": operation.get("message"),
            "history": status.get("history") or [],
        }, _argocd_base_url(context), app_name)


class RollbackArgoCdAppTool:
    name = "rollback_app"
    description = "Rollback an ArgoCD application to a previous deployment history id."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _argocd_base_url(context)
        app_name = _resolve_argocd_application(context, params)
        if not base:
            return {"error": "No ArgoCD URL configured for this project"}
        if not app_name:
            return {"error": "app_name is required and must be allowed"}
        try:
            history_id = int(params.get("history_id"))
        except Exception:
            return {"error": "history_id is required"}
        data = await _http_json(
            "POST",
            f"{base}/api/v1/applications/{quote(app_name, safe='')}/rollback",
            headers=_argocd_headers(context),
            json_body={"id": history_id, "prune": bool(params.get("prune", False))},
        )
        return {"app_name": app_name, "status": "rollback_started", "history_id": history_id, "operation": data}


class ListArgoCdEventsTool:
    name = "list_events"
    description = "List recent events for a single ArgoCD application."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _argocd_base_url(context)
        app_name = _resolve_argocd_application(context, params)
        if not base:
            return {"error": "No ArgoCD URL configured for this project"}
        if not app_name:
            return {"error": "app_name is required and must be allowed"}
        limit = _limit(context, params, default=20, maximum=100)
        data = await _http_json(
            "GET", f"{base}/api/v1/applications/{quote(app_name, safe='')}/events", headers=_argocd_headers(context)
        )
        items = data.get("items") or data.get("events") or []
        return with_application_source({
            "app_name": app_name,
            "count": len(items[:limit]),
            "events": [
                {
                    "reason": item.get("reason"),
                    "message": item.get("message"),
                    "type": item.get("type"),
                    "timestamp": item.get("lastTimestamp") or item.get("eventTime"),
                }
                for item in items[:limit]
            ],
        }, base, app_name)
