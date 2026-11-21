"""Tool definitions for AWS deployment timelines, incident evidence and architecture assessments."""

from __future__ import annotations

AWS_ASSESSMENT_DEFINITIONS: dict[str, dict] = {
    "aws_deployment_timeline": {
        "type": "function",
        "function": {
            "name": "aws_deployment_timeline",
            "description": (
                "Produce a bounded chronological deployment evidence timeline from AWS deployment sources. "
                "The first slice uses read-only CodePipeline execution history."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional CodePipeline names. If omitted, pipelines are listed first.",
                    },
                    "max_executions_per_pipeline": {
                        "type": "integer",
                        "description": "Maximum executions per pipeline, capped server-side.",
                    },
                },
            },
        },
    },
    "aws_incident_evidence_bundle": {
        "type": "function",
        "function": {
            "name": "aws_incident_evidence_bundle",
            "description": (
                "Package selected AWS investigation evidence into an audit-ready structured bundle with basic "
                "secret redaction."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {"type": "string"},
                    "title": {"type": "string"},
                    "severity": {"type": "string"},
                    "topology_snapshot": {"type": "object"},
                    "security_posture": {"type": "object"},
                    "exposure_map": {"type": "object"},
                    "deployment_timeline": {"type": "object"},
                    "cost_report": {"type": "object"},
                    "additional_evidence": {"type": "array", "items": {"type": "object"}},
                    "collect_missing": {
                        "type": "boolean",
                        "description": "Collect missing standard AWS evidence sections before bundling.",
                    },
                    "snapshot_params": {
                        "type": "object",
                        "description": "Optional aws_topology_snapshot params when collect_missing is true.",
                    },
                    "timeline_params": {
                        "type": "object",
                        "description": "Optional aws_deployment_timeline params when collect_missing is true.",
                    },
                },
            },
        },
    },
    "aws_well_architected_assessment": {
        "type": "function",
        "function": {
            "name": "aws_well_architected_assessment",
            "description": (
                "Evaluate AWS evidence against internal Well-Architected-style pillars without creating or "
                "modifying AWS Well-Architected workloads."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topology_snapshot": {"type": "object"},
                    "security_posture": {"type": "object"},
                    "exposure_map": {"type": "object"},
                    "cost_report": {"type": "object"},
                    "deployment_timeline": {"type": "object"},
                    "collect_missing": {"type": "boolean"},
                    "snapshot_params": {"type": "object"},
                    "cost_params": {"type": "object"},
                },
            },
        },
    },
    "aws_trusted_advisor_summary": {
        "type": "function",
        "function": {
            "name": "aws_trusted_advisor_summary",
            "description": (
                "Summarize AWS Trusted Advisor checks and optional check results when AWS Support API access is "
                "available."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "check_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional Trusted Advisor check ids for result lookup.",
                    },
                    "include_results": {
                        "type": "boolean",
                        "description": "Fetch check results in addition to check metadata, capped server-side.",
                    },
                    "max_results": {"type": "integer", "description": "Maximum check results to fetch."},
                    "language": {"type": "string", "description": "Trusted Advisor language, default en."},
                },
            },
        },
    },
}
