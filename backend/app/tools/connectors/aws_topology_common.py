"""Shared helpers for AWS topology connector tools."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_core import _aws_json
from .cloud_common import _aws_allowed
from .common import _normalize_string_list, _string

DEFAULT_TOPOLOGY_SERVICES = (
    "sts",
    "ec2",
    "elbv2",
    "eks",
    "rds",
    "dynamodb",
    "codepipeline",
    "wafv2",
    "lambda",
    "s3",
    "bedrock",
    # extended coverage — each degrades gracefully when unused or unauthorized
    "ecs",
    "apigateway",
    "cloudfront",
    "route53",
    "elasticache",
    "efs",
    "ecr",
    "sqs",
    "sns",
    "secretsmanager",
    "stepfunctions",
    "eventbridge",
    "ec2-instances",
    "networking",
)
KNOWN_TOPOLOGY_SERVICES = set(DEFAULT_TOPOLOGY_SERVICES)


MAX_STRING_CHARS = 500


def bounded_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, min(parsed, maximum))


def tags_from_aws_list(raw: Any) -> dict[str, str]:
    if not isinstance(raw, list):
        return {}
    result: dict[str, str] = {}
    for item in raw:
        if isinstance(item, dict) and item.get("Key") is not None:
            result[str(item.get("Key"))] = str(item.get("Value") or "")
    return result


def compact_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return {"truncated": True, "reason": "max_depth"}
    if isinstance(value, dict):
        return {str(key): compact_payload(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        items = [compact_payload(item, depth=depth + 1) for item in value[:20]]
        if len(value) > 20:
            items.append({"truncated": True, "remaining_items": len(value) - 20})
        return items
    if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
        return value[:MAX_STRING_CHARS] + "...[truncated]"
    return value


def evidence(service: str, operation: str, path: str, *, direct: bool = True) -> dict[str, Any]:
    return {
        "service": service,
        "operation": operation,
        "path": path,
        "direct": direct,
    }


def node_id(node_type: str, value: Any) -> str:
    return f"{node_type}:{_string(value)}"


def requested_services(params: dict[str, Any]) -> list[str]:
    requested = _normalize_string_list(params.get("services"))
    if not requested:
        return list(DEFAULT_TOPOLOGY_SERVICES)
    services = []
    for item in requested:
        normalized = item.lower().replace("_", "-")
        if normalized in KNOWN_TOPOLOGY_SERVICES and normalized not in services:
            services.append(normalized)
    return services or list(DEFAULT_TOPOLOGY_SERVICES)


class TopologyBuilder:
    def __init__(self, *, max_nodes: int) -> None:
        self.max_nodes = max_nodes
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._edge_keys: set[tuple[str, str, str, tuple[tuple[str, Any], ...]]] = set()
        self.warnings: list[dict[str, Any]] = []
        self.services_succeeded: set[str] = set()
        self.services_failed: set[str] = set()
        self.services_skipped: set[str] = set()

    def warn(self, service: str, operation: str, message: str, *, severity: str = "warning") -> None:
        self.warnings.append(
            {
                "service": service,
                "operation": operation,
                "severity": severity,
                "message": message[:1000],
            }
        )

    def add_node(
        self,
        item_id: str,
        *,
        node_type: str,
        label: str,
        service: str,
        region: str,
        arn: str | None = None,
        tags: dict[str, str] | None = None,
        attributes: dict[str, Any] | None = None,
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> None:
        if item_id not in self.nodes and len(self.nodes) >= self.max_nodes:
            if not any(item.get("reason") == "max_nodes" for item in self.warnings):
                self.warnings.append(
                    {
                        "service": "topology",
                        "operation": "add_node",
                        "severity": "warning",
                        "reason": "max_nodes",
                        "message": f"Topology node limit reached at {self.max_nodes} nodes.",
                    }
                )
            return
        existing = self.nodes.get(item_id)
        if existing is None:
            self.nodes[item_id] = {
                "id": item_id,
                "type": node_type,
                "label": label,
                "service": service,
                "region": region,
                "arn": arn,
                "tags": dict(tags or {}),
                "attributes": compact_payload(dict(attributes or {})),
                "evidence": list(evidence_items or []),
            }
            return
        existing["tags"].update(tags or {})
        existing["attributes"].update(compact_payload(dict(attributes or {})))
        existing["evidence"].extend(list(evidence_items or []))

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        *,
        service: str,
        evidence_items: list[dict[str, Any]] | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if not source or not target:
            return
        compact_attributes = compact_payload(dict(attributes or {}))
        key = (source, target, edge_type, _edge_attributes_key(compact_attributes))
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append(
            {
                "source": source,
                "target": target,
                "type": edge_type,
                "service": service,
                "attributes": compact_attributes,
                "evidence": list(evidence_items or []),
            }
        )


async def safe_aws_call(
    context: ToolContext,
    builder: TopologyBuilder,
    service: str,
    command: list[str],
) -> Any | None:
    operation = command[0] if command else ""
    if not _aws_allowed(context, service):
        builder.services_skipped.add(service)
        builder.warn(service, operation, f"AWS service '{service}' is not allowed by project policy.")
        return None
    try:
        result = await _aws_json(context, service, command)
        builder.services_succeeded.add(service)
        return result
    except Exception as exc:
        builder.services_failed.add(service)
        builder.warn(service, operation, str(exc))
        return None


def _edge_attributes_key(attributes: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted((str(key), _hashable_value(value)) for key, value in attributes.items()))


def _hashable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _hashable_value(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(_hashable_value(item) for item in value)
    return value
