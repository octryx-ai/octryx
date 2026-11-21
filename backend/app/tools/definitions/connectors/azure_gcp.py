"""Tool definitions for Azure and Google Cloud resources."""

from __future__ import annotations

AZURE_GCP_DEFINITIONS: dict[str, dict] = {
    "list_azure_resource_groups": {
        "type": "function",
        "function": {
            "name": "list_azure_resource_groups",
            "description": "List Azure resource groups in configured subscriptions",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_azure_aks_clusters": {
        "type": "function",
        "function": {
            "name": "list_azure_aks_clusters",
            "description": "List AKS clusters in configured Azure subscriptions",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_azure_vms": {
        "type": "function",
        "function": {
            "name": "list_azure_vms",
            "description": "List Azure virtual machines",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
    "start_azure_vm": {
        "type": "function",
        "function": {
            "name": "start_azure_vm",
            "description": "Start an Azure VM with approval",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string"},
                    "resource_group": {"type": "string"},
                    "vm_name": {"type": "string"},
                },
                "required": ["subscription_id", "resource_group", "vm_name"],
            },
        },
    },
    "stop_azure_vm": {
        "type": "function",
        "function": {
            "name": "stop_azure_vm",
            "description": "Stop an Azure VM with approval",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string"},
                    "resource_group": {"type": "string"},
                    "vm_name": {"type": "string"},
                },
                "required": ["subscription_id", "resource_group", "vm_name"],
            },
        },
    },
    "get_azure_monitor_alerts": {
        "type": "function",
        "function": {
            "name": "get_azure_monitor_alerts",
            "description": "Get Azure Monitor alerts",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
    "get_azure_monitor_metrics": {
        "type": "function",
        "function": {
            "name": "get_azure_monitor_metrics",
            "description": "Get Azure Monitor metrics for a resource",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {"type": "string"},
                    "metric_name": {"type": "string"},
                    "metric_names": {"type": "array", "items": {"type": "string"}},
                    "timespan": {"type": "string"},
                },
                "required": ["resource_id"],
            },
        },
    },
    "get_azure_cost": {
        "type": "function",
        "function": {
            "name": "get_azure_cost",
            "description": "Get Azure cost management data",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "granularity": {"type": "string"},
                },
            },
        },
    },
    "list_gcp_projects": {
        "type": "function",
        "function": {
            "name": "list_gcp_projects",
            "description": "List accessible GCP projects",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_gcp_gke_clusters": {
        "type": "function",
        "function": {
            "name": "list_gcp_gke_clusters",
            "description": "List GKE clusters in the configured GCP project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_gcp_compute_instances": {
        "type": "function",
        "function": {
            "name": "list_gcp_compute_instances",
            "description": "List Compute Engine instances",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "limit": {"type": "integer"}},
            },
        },
    },
    "get_gcp_compute_logs": {
        "type": "function",
        "function": {
            "name": "get_gcp_compute_logs",
            "description": "Get Cloud Logging entries for Compute Engine",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "instance_id": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_gcp_cloud_run_services": {
        "type": "function",
        "function": {
            "name": "list_gcp_cloud_run_services",
            "description": "List Cloud Run services",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "limit": {"type": "integer"}},
            },
        },
    },
    "get_gcp_cloud_run_logs": {
        "type": "function",
        "function": {
            "name": "get_gcp_cloud_run_logs",
            "description": "Get Cloud Logging entries for Cloud Run",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "service_name": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["service_name"],
            },
        },
    },
}
