"""Tool definitions for AWS topology, drift, security posture, network path and exposure analysis."""

from __future__ import annotations

AWS_TOPOLOGY_DEFINITIONS: dict[str, dict] = {
    "aws_topology_snapshot": {
        "type": "function",
        "function": {
            "name": "aws_topology_snapshot",
            "description": (
                "Return a bounded, read-only, diagram-ready AWS topology graph with nodes, edges, evidence and "
                "warnings. WHEN: always call this FIRST for AWS architecture/topology diagrams or broad AWS "
                "platform overviews — its diagram_brief is the only valid relationship evidence for "
                "create_diagram. WHEN NOT: do not draw AWS diagrams from memory or prose without this "
                "snapshot, and do not use it for non-AWS diagrams."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "services": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "OMIT for full default coverage (recommended - includes networking, compute, data, "
                            "DNS, and event services). Set only when the user explicitly restricts the scope to "
                            "specific services (e.g. ['ec2', 'rds'])."
                        ),
                    },
                    "regions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional AWS regions to inspect (max 4, e.g. ['eu-central-1', 'eu-west-1']). "
                            "Defaults to the configured region; set only when the user asks for other regions."
                        ),
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "Maximum items to inspect per AWS API result, capped server-side.",
                    },
                    "max_nodes": {
                        "type": "integer",
                        "description": "Maximum topology nodes returned, capped server-side.",
                    },
                    "waf_scope": {
                        "type": "string",
                        "description": "WAFv2 scope for Web ACL discovery: REGIONAL or CLOUDFRONT.",
                    },
                    "diagram_brief": {
                        "type": "boolean",
                        "description": (
                            "Include a compact model-facing node and edge brief for draw.io topology diagrams."
                        ),
                    },
                    "diagram_detail": {
                        "type": "string",
                        "enum": ["compact", "full"],
                        "description": (
                            "Diagram brief size. Use compact for small views and full when the user asks for a "
                            "full or complete topology overview."
                        ),
                    },
                },
            },
        },
    },
    "aws_topology_diff": {
        "type": "function",
        "function": {
            "name": "aws_topology_diff",
            "description": (
                "Compare AWS topology snapshots and report added, removed and changed nodes and edges with "
                "severity, service grouping and evidence. If candidate_snapshot is omitted, a current snapshot is "
                "collected with aws_topology_snapshot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "baseline_snapshot": {
                        "type": "object",
                        "description": "Required baseline aws_topology_snapshot output.",
                    },
                    "candidate_snapshot": {
                        "type": "object",
                        "description": "Optional candidate aws_topology_snapshot output.",
                    },
                    "snapshot_params": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot params when candidate_snapshot is omitted.",
                    },
                },
                "required": ["baseline_snapshot"],
            },
        },
    },
    "aws_runtime_vs_iac_drift": {
        "type": "function",
        "function": {
            "name": "aws_runtime_vs_iac_drift",
            "description": (
                "Compare expected IaC topology against live AWS runtime topology and report missing, unmanaged "
                "and changed resources or relationships with severity and evidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "iac_snapshot": {
                        "type": "object",
                        "description": "Expected IaC topology in aws_topology_snapshot-compatible shape.",
                    },
                    "iac_resources": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Simplified expected IaC resources when a full topology snapshot is absent.",
                    },
                    "runtime_snapshot": {
                        "type": "object",
                        "description": "Optional live/runtime topology snapshot. If omitted, one is collected.",
                    },
                    "snapshot_params": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot params used when runtime_snapshot is omitted.",
                    },
                },
            },
        },
    },
    "aws_security_posture_summary": {
        "type": "function",
        "function": {
            "name": "aws_security_posture_summary",
            "description": (
                "Summarize AWS security posture from topology evidence, including public ingress, internet-facing "
                "endpoints, tag governance gaps and collection coverage gaps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topology_snapshot": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot output. If omitted, one is collected.",
                    },
                    "snapshot_params": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot params when topology_snapshot is omitted.",
                    },
                },
            },
        },
    },
    "aws_network_path_analyzer": {
        "type": "function",
        "function": {
            "name": "aws_network_path_analyzer",
            "description": (
                "Analyze static AWS topology relationships between two nodes without sending active network "
                "traffic. Use for explainable reachability and exposure investigations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topology_snapshot": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot output. If omitted, one is collected.",
                    },
                    "source_node_id": {"type": "string", "description": "Topology node id for source."},
                    "target_node_id": {"type": "string", "description": "Topology node id for target."},
                    "source_label": {"type": "string", "description": "Source label fallback when id is unknown."},
                    "target_label": {"type": "string", "description": "Target label fallback when id is unknown."},
                    "max_depth": {"type": "integer", "description": "Maximum relationship hops to inspect."},
                    "snapshot_params": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot params when topology_snapshot is omitted.",
                    },
                },
            },
        },
    },
    "aws_exposure_map": {
        "type": "function",
        "function": {
            "name": "aws_exposure_map",
            "description": (
                "Build a visualizable AWS public exposure map from topology evidence, including public ingress "
                "rules and internet-facing runtime nodes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topology_snapshot": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot output. If omitted, one is collected.",
                    },
                    "snapshot_params": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot params when topology_snapshot is omitted.",
                    },
                },
            },
        },
    },
}
