"""Deep wiring edges for the AWS topology snapshot."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, evidence, safe_aws_call
from .common import _string

_MAX_ZONES_WITH_RECORDS = 3
# Record sets are edge evidence, not nodes: a small caller-provided max_items
# (node budget) must not cut the record scan short — real zones list ACM
# validation CNAMEs (_acme-challenge...) before the interesting alias records.
_MAX_RECORDS_PER_ZONE = 300


async def collect_deep_edges(
    context: ToolContext,
    builder: TopologyBuilder,
    *,
    region: str,
    max_items: int,
    services: set[str],
    include_global: bool,
) -> None:
    if "lambda" in services:
        await _wire_lambda_event_sources(context, builder, max_items)
    if "sns" in services:
        await _wire_sns_subscriptions(context, builder, max_items)
    if include_global and "route53" in services:
        await _wire_route53_records(context, builder, max_items)
    if include_global and "cloudfront" in services:
        _wire_cloudfront_origins(builder)


def _nodes(builder: TopologyBuilder) -> list[dict[str, Any]]:
    return list(builder.nodes.values())


def _index_by_arn(builder: TopologyBuilder) -> dict[str, str]:
    return {
        str(node.get("arn") or ""): str(node.get("id"))
        for node in _nodes(builder)
        if node.get("arn")
    }


def _index_by_type_label(builder: TopologyBuilder, node_type: str) -> dict[str, str]:
    return {
        str(node.get("label") or ""): str(node.get("id"))
        for node in _nodes(builder)
        if str(node.get("type") or "") == node_type
    }


def _index_by_domain(builder: TopologyBuilder) -> dict[str, str]:
    index: dict[str, str] = {}
    for node in _nodes(builder):
        attributes = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
        domain = str(attributes.get("dns_name") or attributes.get("domain") or "").strip().lower()
        if domain:
            index[domain.rstrip(".")] = str(node.get("id"))
    return index


def _resolve_domain(index: dict[str, str], domain: str) -> str:
    value = str(domain or "").strip().lower().rstrip(".")
    # Route 53 alias records point at ALBs via the dualstack. prefix.
    if value.startswith("dualstack."):
        value = value[len("dualstack.") :]
    return index.get(value, "")


def _source_node_for_arn(builder: TopologyBuilder, arn: str) -> str:
    by_arn = _index_by_arn(builder)
    if arn in by_arn:
        return by_arn[arn]
    parts = arn.split(":")
    service = parts[2] if len(parts) > 2 else ""
    resource = parts[5] if len(parts) > 5 else ""
    if service == "sqs":
        return _index_by_type_label(builder, "sqs_queue").get(resource, "")
    if service == "dynamodb" and resource.startswith("table/"):
        table = resource.split("/", 2)[1] if "/" in resource else ""
        return _index_by_type_label(builder, "dynamodb_table").get(table, "")
    return ""


async def _wire_lambda_event_sources(
    context: ToolContext, builder: TopologyBuilder, max_items: int
) -> None:
    data = (await safe_aws_call(context, builder, "lambda", ["list-event-source-mappings"])) or {}
    by_arn = _index_by_arn(builder)
    for mapping in (data.get("EventSourceMappings") or [])[:max_items]:
        source_arn = _string(mapping.get("EventSourceArn"))
        function_arn = _string(mapping.get("FunctionArn"))
        source = _source_node_for_arn(builder, source_arn) if source_arn else ""
        target = by_arn.get(function_arn, "")
        if not source or not target:
            continue
        builder.add_edge(
            source,
            target,
            "triggers",
            service="lambda",
            evidence_items=[evidence("lambda", "list-event-source-mappings", "EventSourceArn")],
            attributes={"state": mapping.get("State")},
        )


async def _wire_sns_subscriptions(
    context: ToolContext, builder: TopologyBuilder, max_items: int
) -> None:
    data = (await safe_aws_call(context, builder, "sns", ["list-subscriptions"])) or {}
    by_arn = _index_by_arn(builder)
    for subscription in (data.get("Subscriptions") or [])[:max_items]:
        topic = by_arn.get(_string(subscription.get("TopicArn")), "")
        endpoint_arn = _string(subscription.get("Endpoint"))
        target = _source_node_for_arn(builder, endpoint_arn) if endpoint_arn.startswith("arn:") else ""
        if not topic or not target:
            continue
        builder.add_edge(
            topic,
            target,
            "delivers_to",
            service="sns",
            evidence_items=[evidence("sns", "list-subscriptions", "Endpoint")],
            attributes={"protocol": subscription.get("Protocol")},
        )


async def _wire_route53_records(
    context: ToolContext, builder: TopologyBuilder, max_items: int
) -> None:
    zones = [node for node in _nodes(builder) if str(node.get("type") or "") == "route53_zone"]
    domain_index = _index_by_domain(builder)
    for zone in zones[:_MAX_ZONES_WITH_RECORDS]:
        zone_id = str(zone.get("id") or "")
        raw_zone_id = str(zone.get("label") or "")
        attributes = zone.get("attributes") if isinstance(zone.get("attributes"), dict) else {}
        hosted_zone_id = str(attributes.get("hosted_zone_id") or "").strip()
        if not hosted_zone_id:
            continue
        data = (
            await safe_aws_call(
                context,
                builder,
                "route53",
                ["list-resource-record-sets", "--hosted-zone-id", hosted_zone_id],
            )
        ) or {}
        for record in (data.get("ResourceRecordSets") or [])[:_MAX_RECORDS_PER_ZONE]:
            if str(record.get("Type") or "") not in {"A", "AAAA", "CNAME"}:
                continue
            targets = []
            alias = record.get("AliasTarget") if isinstance(record.get("AliasTarget"), dict) else {}
            if alias.get("DNSName"):
                targets.append(str(alias["DNSName"]))
            for item in record.get("ResourceRecords") or []:
                value = str((item or {}).get("Value") or "")
                if value:
                    targets.append(value)
            for target_domain in targets:
                target = _resolve_domain(domain_index, target_domain)
                if not target:
                    continue
                builder.add_edge(
                    zone_id,
                    target,
                    "resolves_to",
                    service="route53",
                    evidence_items=[
                        evidence("route53", "list-resource-record-sets", "AliasTarget.DNSName")
                    ],
                    attributes={"record_name": _string(record.get("Name")).rstrip(".") or raw_zone_id},
                )


def _wire_cloudfront_origins(builder: TopologyBuilder) -> None:
    domain_index = _index_by_domain(builder)
    buckets = _index_by_type_label(builder, "s3_bucket")
    for node in _nodes(builder):
        if str(node.get("type") or "") != "cloudfront_distribution":
            continue
        attributes = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
        for origin in attributes.get("origin_domains") or []:
            origin_domain = str(origin or "").strip().lower().rstrip(".")
            target = _resolve_domain(domain_index, origin_domain)
            if not target and ".s3" in origin_domain:
                target = buckets.get(origin_domain.split(".s3", 1)[0], "")
            if not target:
                continue
            builder.add_edge(
                str(node.get("id")),
                target,
                "routes_to",
                service="cloudfront",
                evidence_items=[evidence("cloudfront", "list-distributions", "Origins")],
                attributes={"destination": "origin"},
            )
