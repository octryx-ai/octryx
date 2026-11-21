"""Tool definitions for listing and describing Kubernetes resources."""

from __future__ import annotations

KUBERNETES_RESOURCE_DEFINITIONS: dict[str, dict] = {
    "list_k8s_pods": {
        "type": "function",
        "function": {
            "name": "list_k8s_pods",
            "description": "List all pods in a namespace with their status, restarts and age",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "label_selector": {"type": "string", "description": "Filter pods by label, e.g. app=nginx"},
                },
                "required": ["namespace"],
            },
        },
    },
    "describe_k8s_pod": {
        "type": "function",
        "function": {
            "name": "describe_k8s_pod",
            "description": "Get detailed information about a specific pod including conditions, containers, resource requests/limits and state",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "pod": {"type": "string"},
                },
                "required": ["namespace", "pod"],
            },
        },
    },
    "list_k8s_services": {
        "type": "function",
        "function": {
            "name": "list_k8s_services",
            "description": "List services in a namespace with their type, cluster IP, ports and selectors",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_nodes": {
        "type": "function",
        "function": {
            "name": "list_k8s_nodes",
            "description": "List cluster nodes with their status, roles, instance type, capacity and conditions",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    "get_k8s_configmap": {
        "type": "function",
        "function": {
            "name": "get_k8s_configmap",
            "description": "Get a ConfigMap by name, or list all ConfigMaps in a namespace",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "name": {"type": "string", "description": "ConfigMap name. Omit to list all ConfigMaps."},
                },
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_ingresses": {
        "type": "function",
        "function": {
            "name": "list_k8s_ingresses",
            "description": "List ingresses in a namespace with their hosts, paths and backends",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "get_k8s_resource_usage": {
        "type": "function",
        "function": {
            "name": "get_k8s_resource_usage",
            "description": "Get CPU and memory usage of pods in a namespace from the metrics API (requires metrics-server)",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "describe_k8s_deployment": {
        "type": "function",
        "function": {
            "name": "describe_k8s_deployment",
            "description": "Get detailed deployment info: strategy, conditions, rollout status, replicas, containers, resource requests/limits",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "name": {"type": "string", "description": "Deployment name"},
                },
                "required": ["namespace", "name"],
            },
        },
    },
    "describe_k8s_node": {
        "type": "function",
        "function": {
            "name": "describe_k8s_node",
            "description": "Get detailed node info: conditions, addresses, capacity, allocatable resources, system info, taints",
            "parameters": {
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Node name"},
                },
                "required": ["node"],
            },
        },
    },
    "list_k8s_statefulsets": {
        "type": "function",
        "function": {
            "name": "list_k8s_statefulsets",
            "description": "List StatefulSets in a namespace with their replicas, ready count and update strategy",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_daemonsets": {
        "type": "function",
        "function": {
            "name": "list_k8s_daemonsets",
            "description": "List DaemonSets in a namespace with desired, ready and available counts",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_jobs": {
        "type": "function",
        "function": {
            "name": "list_k8s_jobs",
            "description": "List Jobs in a namespace with completion status, succeeded/failed counts and duration",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_cronjobs": {
        "type": "function",
        "function": {
            "name": "list_k8s_cronjobs",
            "description": "List CronJobs in a namespace with schedule, last run time and suspend status",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_pvcs": {
        "type": "function",
        "function": {
            "name": "list_k8s_pvcs",
            "description": "List PersistentVolumeClaims in a namespace with capacity, access modes, storage class and bound status",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_endpoints": {
        "type": "function",
        "function": {
            "name": "list_k8s_endpoints",
            "description": "List Endpoints in a namespace to check service-to-pod connectivity. Shows ready and not-ready addresses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "service": {"type": "string", "description": "Filter to a specific service name. Omit to list all."},
                },
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_network_policies": {
        "type": "function",
        "function": {
            "name": "list_k8s_network_policies",
            "description": "List NetworkPolicies in a namespace with pod selectors, ingress and egress rules",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_hpas": {
        "type": "function",
        "function": {
            "name": "list_k8s_hpas",
            "description": "List HorizontalPodAutoscalers in a namespace with current/desired replicas, min/max and scaling conditions",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
    "list_k8s_secrets": {
        "type": "function",
        "function": {
            "name": "list_k8s_secrets",
            "description": "List Secrets in a namespace (metadata only: names, types, data key names - no actual secret values)",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
            },
        },
    },
}
