"""GCP connector tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.outbound_egress import CONNECTION_GCP

from ..context import ToolContext
from .cloud_common import _gcp_allowed
from .common import _headers_with_bearer, _limit, _string, connection_http_json
from .gcp_core import (
    _gcp_access_token,
    _gcp_compute_base_url,
    _gcp_container_base_url,
    _gcp_logging_base_url,
    _gcp_monitoring_base_url,
    _gcp_resourcemanager_base_url,
    _gcp_run_base_url,
    _gcp_sqladmin_base_url,
)

#: This module's HTTP helpers use the gcp egress rule.
_http_json = connection_http_json(CONNECTION_GCP)


class ListGcpProjectsTool:
    name = "list_gcp_projects"
    description = "List accessible GCP projects."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        token = await _gcp_access_token(context)
        data = await _http_json(
            "GET",
            f"{_gcp_resourcemanager_base_url(context)}/v1/projects",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
            params={"pageSize": _limit(context, params, default=50, maximum=200)},
        )
        projects = data.get("projects") or []
        return {
            "count": len(projects),
            "projects": [
                {
                    "project_id": item.get("projectId"),
                    "name": item.get("name"),
                    "project_number": item.get("projectNumber"),
                    "lifecycle_state": item.get("lifecycleState"),
                }
                for item in projects
            ],
        }


class ListGcpGkeClustersTool:
    name = "list_gcp_gke_clusters"
    description = "List GKE clusters in the configured GCP project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project_id = _string(params.get("project_id") or context.project_config.get("gcp_project_id"))
        if not project_id:
            return {"error": "project_id is required"}
        token = await _gcp_access_token(context)
        data = await _http_json(
            "GET",
            f"{_gcp_container_base_url(context)}/v1/projects/{project_id}/locations/-/clusters",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
        )
        clusters = data.get("clusters") or []
        return {
            "project_id": project_id,
            "count": len(clusters),
            "clusters": [
                {
                    "name": item.get("name"),
                    "location": item.get("location"),
                    "status": item.get("status"),
                    "endpoint": item.get("endpoint"),
                    "current_master_version": item.get("currentMasterVersion"),
                }
                for item in clusters[: _limit(context, params, default=50, maximum=200)]
            ],
        }


class ListGcpComputeInstancesTool:
    name = "list_gcp_compute_instances"
    description = "List Compute Engine instances for a GCP project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _gcp_allowed(context, "compute"):
            return {"error": "GCP service 'compute' is not allowed"}
        project_id = _string(params.get("project_id") or context.project_config.get("gcp_project_id"))
        if not project_id:
            return {"error": "project_id is required"}
        token = await _gcp_access_token(context)
        data = await _http_json(
            "GET",
            f"{_gcp_compute_base_url(context)}/compute/v1/projects/{project_id}/aggregated/instances",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
        )
        instances: list[dict[str, Any]] = []
        for scoped in (data.get("items") or {}).values():
            for item in scoped.get("instances") or []:
                instances.append(
                    {
                        "name": item.get("name"),
                        "id": item.get("id"),
                        "zone": item.get("zone"),
                        "status": item.get("status"),
                        "machine_type": item.get("machineType"),
                    }
                )
        return {
            "project_id": project_id,
            "count": len(instances),
            "instances": instances[: _limit(context, params, default=50, maximum=200)],
        }


class GetGcpComputeLogsTool:
    name = "get_gcp_compute_logs"
    description = "Query Cloud Logging entries for Compute Engine instances."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _gcp_allowed(context, "logging"):
            return {"error": "GCP service 'logging' is not allowed"}
        project_id = _string(params.get("project_id") or context.project_config.get("gcp_project_id"))
        if not project_id:
            return {"error": "project_id is required"}
        token = await _gcp_access_token(context)
        instance_id = _string(params.get("instance_id"))
        query = _string(params.get("query"))
        instance_clause = f' AND resource.labels.instance_id="{instance_id}"' if instance_id else ""
        log_filter = query or f'resource.type="gce_instance"{instance_clause}'
        data = await _http_json(
            "POST",
            f"{_gcp_logging_base_url(context)}/v2/entries:list",
            headers=_headers_with_bearer(
                token, extra={"Accept": "application/json", "Content-Type": "application/json"}
            ),
            json_body={
                "resourceNames": [f"projects/{project_id}"],
                "filter": log_filter,
                "pageSize": _limit(context, params, default=20, maximum=100),
            },
        )
        entries = data.get("entries") or []
        return {"project_id": project_id, "count": len(entries), "entries": entries}


class ListGcpCloudSqlInstancesTool:
    name = "list_gcp_cloud_sql_instances"
    description = "List Cloud SQL instances for a GCP project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _gcp_allowed(context, "cloudsql"):
            return {"error": "GCP service 'cloudsql' is not allowed"}
        project_id = _string(params.get("project_id") or context.project_config.get("gcp_project_id"))
        if not project_id:
            return {"error": "project_id is required"}
        token = await _gcp_access_token(context)
        data = await _http_json(
            "GET",
            f"{_gcp_sqladmin_base_url(context)}/sql/v1beta4/projects/{project_id}/instances",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
        )
        instances = data.get("items") or []
        return {
            "project_id": project_id,
            "count": len(instances),
            "instances": [
                {
                    "name": item.get("name"),
                    "database_version": item.get("databaseVersion"),
                    "region": item.get("region"),
                    "state": item.get("state"),
                }
                for item in instances[: _limit(context, params, default=50, maximum=200)]
            ],
        }


class GetGcpCloudSqlMetricsTool:
    name = "get_gcp_cloud_sql_metrics"
    description = "Get Cloud Monitoring metrics for a Cloud SQL instance."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _gcp_allowed(context, "monitoring"):
            return {"error": "GCP service 'monitoring' is not allowed"}
        project_id = _string(params.get("project_id") or context.project_config.get("gcp_project_id"))
        database_id = _string(params.get("database_id") or params.get("instance_id"))
        metric_type = _string(params.get("metric_type") or "cloudsql.googleapis.com/database/cpu/utilization")
        if not project_id or not database_id:
            return {"error": "project_id and database_id are required"}
        token = await _gcp_access_token(context)
        data = await _http_json(
            "GET",
            f"{_gcp_monitoring_base_url(context)}/v3/projects/{project_id}/timeSeries",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
            params={
                "filter": f'metric.type="{metric_type}" AND resource.label."database_id"="{database_id}"',
                "interval.endTime": datetime.now(UTC).isoformat(),
                "interval.startTime": (datetime.now(UTC) - timedelta(hours=int(params.get("hours") or 1))).isoformat(),
            },
        )
        series = data.get("timeSeries") or []
        return {
            "project_id": project_id,
            "database_id": database_id,
            "metric_type": metric_type,
            "count": len(series),
            "series": series,
        }


class ListGcpCloudRunServicesTool:
    name = "list_gcp_cloud_run_services"
    description = "List Cloud Run services for a GCP project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _gcp_allowed(context, "cloudrun"):
            return {"error": "GCP service 'cloudrun' is not allowed"}
        project_id = _string(params.get("project_id") or context.project_config.get("gcp_project_id"))
        if not project_id:
            return {"error": "project_id is required"}
        token = await _gcp_access_token(context)
        data = await _http_json(
            "GET",
            f"{_gcp_run_base_url(context)}/v2/projects/{project_id}/locations/-/services",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
        )
        services = data.get("services") or []
        return {
            "project_id": project_id,
            "count": len(services),
            "services": [
                {
                    "name": item.get("name"),
                    "uri": item.get("uri"),
                    "ingress": item.get("ingress"),
                    "reconciling": item.get("reconciling"),
                }
                for item in services[: _limit(context, params, default=50, maximum=200)]
            ],
        }


class GetGcpCloudRunLogsTool:
    name = "get_gcp_cloud_run_logs"
    description = "Query Cloud Logging entries for Cloud Run services."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _gcp_allowed(context, "logging"):
            return {"error": "GCP service 'logging' is not allowed"}
        project_id = _string(params.get("project_id") or context.project_config.get("gcp_project_id"))
        service_name = _string(params.get("service_name"))
        if not project_id or not service_name:
            return {"error": "project_id and service_name are required"}
        token = await _gcp_access_token(context)
        log_filter = (
            _string(params.get("query"))
            or f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service_name}"'
        )
        data = await _http_json(
            "POST",
            f"{_gcp_logging_base_url(context)}/v2/entries:list",
            headers=_headers_with_bearer(
                token, extra={"Accept": "application/json", "Content-Type": "application/json"}
            ),
            json_body={
                "resourceNames": [f"projects/{project_id}"],
                "filter": log_filter,
                "pageSize": _limit(context, params, default=20, maximum=100),
            },
        )
        entries = data.get("entries") or []
        return {"project_id": project_id, "service_name": service_name, "count": len(entries), "entries": entries}
