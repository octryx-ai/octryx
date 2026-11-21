"""AWS security posture summary connector tool."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_topology import build_aws_topology_snapshot

PUBLIC_CIDRS = {"0.0.0.0/0", "::/0"}
SENSITIVE_PORTS = {22, 3389, 5432, 3306, 6379, 9200, 9300}
TAG_REQUIRED_NODE_TYPES = {"eks_cluster", "rds_instance", "load_balancer", "s3_bucket", "lambda_function"}


def _nodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("nodes")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _edges(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("edges")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _node_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in _nodes(snapshot) if item.get("id")}


def _severity_for_public_ingress(edge: dict[str, Any]) -> str:
    attrs = edge.get("attributes") if isinstance(edge.get("attributes"), dict) else {}
    ports = [attrs.get("from_port"), attrs.get("to_port")]
    try:
        parsed_ports = {int(port) for port in ports if port is not None}
    except (TypeError, ValueError):
        parsed_ports = set()
    if parsed_ports & SENSITIVE_PORTS:
        return "critical"
    if not parsed_ports:
        return "high"
    return "medium"


def _finding(
    category: str,
    severity: str,
    title: str,
    *,
    node: dict[str, Any] | None = None,
    edge: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "title": title,
        "node_id": node.get("id") if node else None,
        "node_type": node.get("type") if node else None,
        "service": (node or edge or {}).get("service"),
        "details": details or {},
        "evidence": {
            "node": list((node or {}).get("evidence") or []),
            "edge": list((edge or {}).get("evidence") or []),
        },
    }


def _public_ingress_findings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = _node_map(snapshot)
    findings = []
    for edge in _edges(snapshot):
        if edge.get("type") != "allows_ingress_to":
            continue
        source = nodes.get(str(edge.get("source"))) or {}
        target = nodes.get(str(edge.get("target"))) or {}
        if source.get("label") not in PUBLIC_CIDRS:
            continue
        attrs = edge.get("attributes") if isinstance(edge.get("attributes"), dict) else {}
        findings.append(
            _finding(
                "public_ingress",
                _severity_for_public_ingress(edge),
                f"Public ingress allowed to {target.get('label') or target.get('id')}",
                node=target,
                edge=edge,
                details={
                    "cidr": source.get("label"),
                    "protocol": attrs.get("protocol"),
                    "from_port": attrs.get("from_port"),
                    "to_port": attrs.get("to_port"),
                },
            )
        )
    return findings


def _internet_facing_lb_findings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for node in _nodes(snapshot):
        attrs = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
        if node.get("type") == "load_balancer" and attrs.get("scheme") == "internet-facing":
            findings.append(
                _finding(
                    "public_endpoint",
                    "medium",
                    f"Internet-facing load balancer: {node.get('label') or node.get('id')}",
                    node=node,
                    details={"scheme": attrs.get("scheme"), "dns_name": attrs.get("dns_name")},
                )
            )
    return findings


def _untagged_resource_findings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for node in _nodes(snapshot):
        if node.get("type") not in TAG_REQUIRED_NODE_TYPES:
            continue
        tags = node.get("tags") if isinstance(node.get("tags"), dict) else {}
        if tags:
            continue
        findings.append(
            _finding(
                "tag_governance",
                "low",
                f"Governance tags missing on {node.get('label') or node.get('id')}",
                node=node,
                details={"expected": "at least one governance tag"},
            )
        )
    return findings


def _coverage_findings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    scope = snapshot.get("scope") if isinstance(snapshot.get("scope"), dict) else {}
    for service in scope.get("services_failed") or []:
        findings.append(
            _finding(
                "coverage_gap",
                "medium",
                f"AWS topology collection failed for {service}",
                details={"service": service},
            )
        )
    for service in scope.get("services_skipped") or []:
        findings.append(
            _finding(
                "coverage_gap",
                "low",
                f"AWS topology collection skipped for {service}",
                details={"service": service},
            )
        )
    return findings


def _summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity") or "unknown")
        category = str(finding.get("category") or "unknown")
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "finding_count": len(findings),
        "by_severity": by_severity,
        "by_category": by_category,
        "has_critical": by_severity.get("critical", 0) > 0,
    }


async def build_aws_security_posture_summary(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    topology = params.get("topology_snapshot") if isinstance(params.get("topology_snapshot"), dict) else None
    topology_source = "provided" if topology else "collected"
    if topology is None:
        snapshot_params = params.get("snapshot_params") if isinstance(params.get("snapshot_params"), dict) else {}
        topology = await build_aws_topology_snapshot(context, snapshot_params)

    findings = [
        *_public_ingress_findings(topology),
        *_internet_facing_lb_findings(topology),
        *_untagged_resource_findings(topology),
        *_coverage_findings(topology),
    ]
    return {
        "status": "ok",
        "topology_source": topology_source,
        "account_id": topology.get("account_id"),
        "region": topology.get("region"),
        "summary": _summary(findings),
        "findings": findings,
        "warnings": list(topology.get("warnings") or []),
    }


class AwsSecurityPostureSummaryTool:
    name = "aws_security_posture_summary"
    description = (
        "Summarize AWS security posture from topology evidence, including public ingress, internet-facing endpoints, "
        "tag governance gaps and collection coverage gaps."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await build_aws_security_posture_summary(context, params or {})
