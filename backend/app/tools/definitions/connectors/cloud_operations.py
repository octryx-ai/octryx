"""Tool definitions for ServiceNow incident listing and generic AWS read, action, config and cost tools."""

from __future__ import annotations

CLOUD_OPERATION_DEFINITIONS: dict[str, dict] = {
    "list_servicenow_incidents": {
        "type": "function",
        "function": {
            "name": "list_servicenow_incidents",
            "description": "List ServiceNow incidents",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "ServiceNow sysparm_query filter"},
                    "fields": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_aws_eks_clusters": {
        "type": "function",
        "function": {
            "name": "list_aws_eks_clusters",
            "description": "List EKS clusters in the configured AWS account and region",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "aws_read_operation": {
        "type": "function",
        "function": {
            "name": "aws_read_operation",
            "description": (
                "Run a constrained read-only AWS CLI operation using runtime IRSA credentials. "
                "Use for broad AWS inspection across services. Secret-value reads and mutating actions are blocked."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "AWS CLI service name, for example eks, rds, elbv2, logs, cloudwatch, sts",
                    },
                    "operation": {
                        "type": "string",
                        "description": "AWS CLI operation, for example describe-cluster or filter-log-events",
                    },
                    "arguments": {
                        "description": "CLI arguments as an object with snake_case/kebab-case keys, or an argv array",
                        "oneOf": [
                            {"type": "object"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                    "timeout_seconds": {"type": "integer"},
                    "max_items": {"type": "integer"},
                },
                "required": ["service", "operation"],
            },
        },
    },
    "aws_action_operation": {
        "type": "function",
        "function": {
            "name": "aws_action_operation",
            "description": (
                "Run an explicitly allowed AWS mutating operation using runtime IRSA credentials after approval. "
                "Default allowed action is codepipeline:start-pipeline-execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "AWS CLI service name"},
                    "operation": {"type": "string", "description": "AWS CLI operation name"},
                    "arguments": {
                        "description": "CLI arguments as an object with snake_case/kebab-case keys, or an argv array",
                        "oneOf": [
                            {"type": "object"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                    "reason": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "max_items": {"type": "integer"},
                },
                "required": ["service", "operation"],
            },
        },
    },
    "aws_config_query": {
        "type": "function",
        "function": {
            "name": "aws_config_query",
            "description": (
                "Run a bounded, read-only AWS Config advanced query for normalized inventory and governance "
                "evidence. Prefer templates unless a precise SELECT query is needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "template": {
                        "type": "string",
                        "description": (
                            "Optional template: resource_inventory, ec2_network_inventory, rds_inventory, "
                            "s3_inventory or tag_coverage."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional custom AWS Config SELECT expression. Mutating statements are blocked.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum result rows returned by AWS Config, capped server-side.",
                    },
                    "next_token": {
                        "type": "string",
                        "description": "Optional AWS Config pagination token from a previous result.",
                    },
                },
            },
        },
    },
    "aws_cost_topology_report": {
        "type": "function",
        "function": {
            "name": "aws_cost_topology_report",
            "description": (
                "Map AWS Cost Explorer service and tag costs onto known topology services without claiming "
                "unsupported resource-level attribution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "Inclusive Cost Explorer start date YYYY-MM-DD."},
                    "end": {"type": "string", "description": "Exclusive Cost Explorer end date YYYY-MM-DD."},
                    "granularity": {"type": "string", "description": "MONTHLY, DAILY or HOURLY."},
                    "metric": {"type": "string", "description": "Cost Explorer metric, default UnblendedCost."},
                    "topology_snapshot": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot output for service-to-node mapping.",
                    },
                    "collect_topology": {
                        "type": "boolean",
                        "description": "Collect a current topology snapshot when topology_snapshot is omitted.",
                    },
                    "snapshot_params": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot params used when collect_topology is true.",
                    },
                    "tag_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional Cost Explorer TAG groupings to include, capped server-side.",
                    },
                },
            },
        },
    },
}
