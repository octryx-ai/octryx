"""Kubernetes batch tools: jobs and cron jobs."""

from typing import Any

import httpx

from .context import ToolContext
from .kubernetes import _alert_scoped, _k8s_transport, _resolve_k8s_api_config, _warn_if_tls_disabled


class ListJobs:
    name = "list_k8s_jobs"
    description = "List Jobs in a namespace with their completion status and duration"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_jobs")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/apis/batch/v1/namespaces/{namespace}/jobs", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        items = []
        for job in data.get("items", []):
            status = job.get("status", {})
            conditions = status.get("conditions", [])
            condition_types = [c["type"] for c in conditions if c.get("status") == "True"]
            items.append({
                "name": job["metadata"]["name"],
                "completions": job.get("spec", {}).get("completions"),
                "succeeded": status.get("succeeded", 0),
                "failed": status.get("failed", 0),
                "active": status.get("active", 0),
                "start_time": status.get("startTime"),
                "completion_time": status.get("completionTime"),
                "conditions": condition_types,
            })
        return {"source": "api", "namespace": namespace, "total": len(items), "jobs": items}


class ListCronJobs:
    name = "list_k8s_cronjobs"
    description = "List CronJobs in a namespace with schedule, last run and suspend status"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_cronjobs")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/apis/batch/v1/namespaces/{namespace}/cronjobs", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        items = []
        for cj in data.get("items", []):
            spec = cj.get("spec", {})
            status = cj.get("status", {})
            items.append({
                "name": cj["metadata"]["name"],
                "schedule": spec.get("schedule"),
                "suspend": spec.get("suspend", False),
                "concurrency_policy": spec.get("concurrencyPolicy"),
                "last_schedule_time": status.get("lastScheduleTime"),
                "last_successful_time": status.get("lastSuccessfulTime"),
                "active_jobs": len(status.get("active", [])),
            })
        return {"source": "api", "namespace": namespace, "total": len(items), "cronjobs": items}
