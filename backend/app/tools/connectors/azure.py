"""Azure connector tools."""

from __future__ import annotations

from typing import Any

from app.services.outbound_egress import CONNECTION_AZURE

from ..context import ToolContext
from .cloud_common import _maybe_block_connector_action_with_approval
from .common import _headers_with_bearer, _limit, _normalize_string_list, _string, connection_http_json
from .microsoft_graph import _microsoft_graph_token

#: This module's HTTP helpers use the azure egress rule.
_http_json = connection_http_json(CONNECTION_AZURE)


async def _azure_token(context: ToolContext) -> str:
    return await _microsoft_graph_token(context, scope="https://management.azure.com/.default")


def _azure_subscriptions(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("azure_subscription_ids"))


def _azure_management_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("azure_management_url") or "https://management.azure.com").rstrip("/")


class ListAzureResourceGroupsTool:
    name = "list_azure_resource_groups"
    description = "List Azure resource groups in configured subscriptions."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        subscriptions = _azure_subscriptions(context)
        if not subscriptions:
            return {"error": "No Azure subscriptions configured for this project"}
        token = await _azure_token(context)
        groups: list[dict[str, Any]] = []
        for subscription in subscriptions[:10]:
            data = await _http_json(
                "GET",
                f"https://management.azure.com/subscriptions/{subscription}/resourcegroups",
                headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
                params={"api-version": "2021-04-01"},
            )
            for item in (data.get("value") or [])[: _limit(context, params, default=50, maximum=200)]:
                groups.append(
                    {
                        "subscription_id": subscription,
                        "name": item.get("name"),
                        "location": item.get("location"),
                        "id": item.get("id"),
                    }
                )
        return {"count": len(groups), "resource_groups": groups}


class ListAzureAksClustersTool:
    name = "list_azure_aks_clusters"
    description = "List AKS clusters in configured Azure subscriptions."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        subscriptions = _azure_subscriptions(context)
        if not subscriptions:
            return {"error": "No Azure subscriptions configured for this project"}
        token = await _azure_token(context)
        clusters: list[dict[str, Any]] = []
        for subscription in subscriptions[:10]:
            data = await _http_json(
                "GET",
                f"https://management.azure.com/subscriptions/{subscription}/providers/Microsoft.ContainerService/managedClusters",
                headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
                params={"api-version": "2024-02-01"},
            )
            for item in (data.get("value") or [])[: _limit(context, params, default=50, maximum=200)]:
                clusters.append(
                    {
                        "subscription_id": subscription,
                        "name": item.get("name"),
                        "location": item.get("location"),
                        "resource_group": _string(item.get("id")).split("/resourceGroups/")[1].split("/")[0]
                        if "/resourceGroups/" in _string(item.get("id"))
                        else None,
                        "power_state": (((item.get("properties") or {}).get("powerState")) or {}).get("code"),
                    }
                )
        return {"count": len(clusters), "clusters": clusters}


class ListAzureVirtualMachinesTool:
    name = "list_azure_vms"
    description = "List Azure virtual machines in configured subscriptions."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        subscriptions = _azure_subscriptions(context)
        if not subscriptions:
            return {"error": "No Azure subscriptions configured for this project"}
        token = await _azure_token(context)
        base = _azure_management_base_url(context)
        vms: list[dict[str, Any]] = []
        for subscription in subscriptions[:10]:
            data = await _http_json(
                "GET",
                f"{base}/subscriptions/{subscription}/providers/Microsoft.Compute/virtualMachines",
                headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
                params={"api-version": "2023-09-01"},
            )
            for item in (data.get("value") or [])[: _limit(context, params, default=50, maximum=200)]:
                vms.append(
                    {
                        "subscription_id": subscription,
                        "name": item.get("name"),
                        "location": item.get("location"),
                        "resource_group": _string(item.get("id")).split("/resourceGroups/")[1].split("/")[0]
                        if "/resourceGroups/" in _string(item.get("id"))
                        else None,
                        "id": item.get("id"),
                    }
                )
        return {"count": len(vms), "virtual_machines": vms}


class StartAzureVirtualMachineTool:
    name = "start_azure_vm"
    description = "Start an Azure virtual machine with approval."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        subscription_id = _string(params.get("subscription_id"))
        resource_group = _string(params.get("resource_group"))
        vm_name = _string(params.get("vm_name"))
        if not subscription_id or not resource_group or not vm_name:
            return {"error": "subscription_id, resource_group and vm_name are required"}
        blocked = await _maybe_block_connector_action_with_approval(
            self.name, params, context, title="Azure VM start", summary=f"Start Azure VM {vm_name} in {resource_group}"
        )
        if blocked:
            return blocked
        token = await _azure_token(context)
        base = _azure_management_base_url(context)
        await _http_json(
            "POST",
            f"{base}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines/{vm_name}/start",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
            params={"api-version": "2023-09-01"},
        )
        return {
            "status": "started",
            "subscription_id": subscription_id,
            "resource_group": resource_group,
            "vm_name": vm_name,
        }


class StopAzureVirtualMachineTool:
    name = "stop_azure_vm"
    description = "Stop an Azure virtual machine with approval."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        subscription_id = _string(params.get("subscription_id"))
        resource_group = _string(params.get("resource_group"))
        vm_name = _string(params.get("vm_name"))
        if not subscription_id or not resource_group or not vm_name:
            return {"error": "subscription_id, resource_group and vm_name are required"}
        blocked = await _maybe_block_connector_action_with_approval(
            self.name, params, context, title="Azure VM stop", summary=f"Stop Azure VM {vm_name} in {resource_group}"
        )
        if blocked:
            return blocked
        token = await _azure_token(context)
        base = _azure_management_base_url(context)
        await _http_json(
            "POST",
            f"{base}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines/{vm_name}/deallocate",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
            params={"api-version": "2023-09-01"},
        )
        return {
            "status": "stopped",
            "subscription_id": subscription_id,
            "resource_group": resource_group,
            "vm_name": vm_name,
        }


class GetAzureMonitorAlertsTool:
    name = "get_azure_monitor_alerts"
    description = "Get Azure Monitor alerts for configured subscriptions."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        subscriptions = _azure_subscriptions(context)
        if not subscriptions:
            return {"error": "No Azure subscriptions configured for this project"}
        token = await _azure_token(context)
        base = _azure_management_base_url(context)
        alerts: list[dict[str, Any]] = []
        for subscription in subscriptions[:10]:
            data = await _http_json(
                "GET",
                f"{base}/subscriptions/{subscription}/providers/Microsoft.AlertsManagement/alerts",
                headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
                params={"api-version": "2023-07-12-preview"},
            )
            for item in (data.get("value") or [])[: _limit(context, params, default=50, maximum=200)]:
                alerts.append(
                    {
                        "subscription_id": subscription,
                        "name": item.get("name"),
                        "severity": ((item.get("properties") or {}).get("severity")),
                        "monitor_condition": ((item.get("properties") or {}).get("monitorCondition")),
                    }
                )
        return {"count": len(alerts), "alerts": alerts}


class GetAzureMonitorMetricsTool:
    name = "get_azure_monitor_metrics"
    description = "Get Azure Monitor metrics for a resource."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        resource_id = _string(params.get("resource_id"))
        metric_names = ",".join(
            _normalize_string_list(params.get("metric_names"))
            or [_string(params.get("metric_name") or "Percentage CPU")]
        )
        if not resource_id:
            return {"error": "resource_id is required"}
        token = await _azure_token(context)
        base = _azure_management_base_url(context)
        data = await _http_json(
            "GET",
            f"{base}{resource_id}/providers/microsoft.insights/metrics",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
            params={
                "api-version": "2023-10-01",
                "metricnames": metric_names,
                "timespan": _string(params.get("timespan") or "PT1H"),
            },
        )
        values = data.get("value") or []
        return {"resource_id": resource_id, "count": len(values), "metrics": values}


class GetAzureCostTool:
    name = "get_azure_cost"
    description = "Get Azure cost management data for a subscription."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        subscription_id = _string(params.get("subscription_id")) or (
            _azure_subscriptions(context)[0] if _azure_subscriptions(context) else ""
        )
        if not subscription_id:
            return {"error": "subscription_id is required"}
        token = await _azure_token(context)
        base = _azure_management_base_url(context)
        data = await _http_json(
            "POST",
            f"{base}/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query",
            headers=_headers_with_bearer(
                token, extra={"Accept": "application/json", "Content-Type": "application/json"}
            ),
            params={"api-version": "2023-03-01"},
            json_body={
                "type": "ActualCost",
                "timeframe": _string(params.get("timeframe") or "MonthToDate"),
                "dataset": {
                    "granularity": _string(params.get("granularity") or "Daily"),
                    "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                },
            },
        )
        rows = ((data.get("properties") or {}).get("rows")) or []
        return {"subscription_id": subscription_id, "count": len(rows), "rows": rows}
