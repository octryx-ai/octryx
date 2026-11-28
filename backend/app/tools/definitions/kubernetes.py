"""Tool definitions for kubernetes domain."""

from __future__ import annotations

import copy

from .kubernetes_resources import KUBERNETES_RESOURCE_DEFINITIONS

_KUBERNETES_DIAGNOSIS_DEFINITIONS: dict[str, dict] = {
    "get_k8s_events": {
        "type": "function",
        "function": {
            "name": "get_k8s_events",
            "description": "Get Kubernetes events for a namespace or pod",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "pod": {"type": "string"},
                },
                "required": ["namespace"],
            },
        },
    },
    "get_pod_logs": {
        "type": "function",
        "function": {
            "name": "get_pod_logs",
            "description": "Get logs from a Kubernetes pod",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "pod": {"type": "string"},
                    "container": {"type": "string"},
                    "tail_lines": {"type": "integer"},
                },
                "required": ["namespace", "pod"],
            },
        },
    },
    "list_failed_pods": {
        "type": "function",
        "function": {
            "name": "list_failed_pods",
            "description": "List pods in failed or CrashLoop state",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "get_k8s_deployments": {
        "type": "function",
        "function": {
            "name": "get_k8s_deployments",
            "description": "Get deployment status in a namespace",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "run_kubectl": {
        "type": "function",
        "function": {
            "name": "run_kubectl",
            "description": "Run kubectl with the configured kubeconfig/context for the active project",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "namespace": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["args"],
            },
        },
    },
    "list_k8s_namespaces": {
        "type": "function",
        "function": {
            "name": "list_k8s_namespaces",
            "description": "List all namespaces in the cluster",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    "kubernetes_topology_snapshot": {
        "type": "function",
        "function": {
            "name": "kubernetes_topology_snapshot",
            "description": (
                "Collect a bounded Kubernetes topology graph with namespaces, workloads, pods, services, "
                "ingresses, storage, network policies, nodes, relationships, and a draw.io diagram brief"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Optional namespace scope. Omit when all_namespaces is true.",
                    },
                    "all_namespaces": {
                        "type": "boolean",
                        "description": "Collect namespaced resources across all namespaces when true.",
                    },
                    "diagram_brief": {
                        "type": "boolean",
                        "description": "Return selected_nodes and selected_edges for diagram rendering.",
                    },
                    "diagram_detail": {
                        "type": "string",
                        "enum": ["compact", "full"],
                        "description": "Controls snapshot selection breadth for diagram rendering.",
                    },
                    "max_items": {"type": "integer", "description": "Per-resource collection cap."},
                    "max_nodes": {"type": "integer", "description": "Maximum graph nodes exposed in diagram_brief."},
                },
            },
        },
    },
}


def get_kubernetes_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy({**_KUBERNETES_DIAGNOSIS_DEFINITIONS, **KUBERNETES_RESOURCE_DEFINITIONS})
