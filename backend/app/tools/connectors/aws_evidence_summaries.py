"""One-line summaries of AWS tool results for the evidence salvage message (``aws_evidence_salvage``)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def _payload(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    preview = result.get("preview")
    compact_result = preview.get("compact_result") if isinstance(preview, dict) else None
    return compact_result if isinstance(compact_result, dict) else result


def _inner_result(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    return result if isinstance(result, dict) else payload


def _stringify_identifier(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _first_identifier(item: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = _stringify_identifier(item.get(key))
        if value:
            return value
    return ""


_KNOWN_ITEM_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("clusters", ("name", "clusterName", "cluster_name", "id")),
    ("Clusters", ("name", "clusterName", "cluster_name", "id")),
    ("nodegroups", ("nodegroupName", "name", "id")),
    ("pipelines", ("name", "pipelineName", "pipeline_name", "id")),
    ("DBInstances", ("DBInstanceIdentifier", "identifier", "name", "id")),
    ("instances", ("identifier", "DBInstanceIdentifier", "InstanceId", "name", "id")),
    ("MetricAlarms", ("AlarmName", "name", "alarm_name")),
    ("alarms", ("AlarmName", "name", "alarm_name")),
    ("WebACLs", ("Name", "name", "ARN", "arn")),
    ("web_acls", ("Name", "name", "ARN", "arn")),
    ("Vpcs", ("VpcId", "id", "name", "CidrBlock")),
    ("vpcs", ("VpcId", "id", "name", "CidrBlock")),
    ("SecurityGroups", ("GroupId", "GroupName", "name", "id")),
    ("security_groups", ("GroupId", "GroupName", "name", "id")),
    ("Subnets", ("SubnetId", "id", "CidrBlock")),
    ("subnets", ("SubnetId", "id", "CidrBlock")),
    ("RouteTables", ("RouteTableId", "id")),
    ("route_tables", ("RouteTableId", "id")),
    ("buckets", ("Name", "name")),
    ("Functions", ("FunctionName", "name")),
    ("functions", ("FunctionName", "name")),
    ("trails", ("Name", "TrailARN", "arn")),
    ("Repositories", ("repositoryName", "name")),
    ("repositories", ("repositoryName", "name")),
)


def _items_from_known_payload(payload: dict[str, Any]) -> list[str]:
    candidates: list[str] = []

    result = _inner_result(payload)
    account = _stringify_identifier(result.get("Account"))
    arn = _stringify_identifier(result.get("Arn"))
    if account or arn:
        candidates.append(" / ".join(part for part in (account, arn) if part))

    for key, identifier_keys in _KNOWN_ITEM_KEYS:
        value = payload.get(key)
        if not isinstance(value, list):
            value = result.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                identifier = _first_identifier(item, identifier_keys)
            else:
                identifier = _stringify_identifier(item)
            if identifier:
                candidates.append(identifier)

    return candidates


def _endpoint_access_label(vpc_config: dict[str, Any]) -> str:
    public = vpc_config.get("endpointPublicAccess")
    private = vpc_config.get("endpointPrivateAccess")
    if public is True and private is True:
        return "endpoint public and private"
    if public is True and private is False:
        return "endpoint public only"
    if public is False and private is True:
        return "endpoint private only"
    if public is False and private is False:
        return "endpoint disabled"
    return "endpoint access unknown"


def _sts_summary(prefix: str, service: str, result: dict[str, Any]) -> str:
    if service != "sts" or not (result.get("Account") or result.get("Arn")):
        return ""
    account = _stringify_identifier(result.get("Account")) or "unknown account"
    arn = _stringify_identifier(result.get("Arn"))
    return f"{prefix} -> account {account}" + (f", arn {arn}" if arn else "")


def _eks_summary(prefix: str, service: str, result: dict[str, Any]) -> str:
    cluster = result.get("cluster") if isinstance(result.get("cluster"), dict) else {}
    if service != "eks" or not cluster:
        return ""
    vpc_config = cluster.get("resourcesVpcConfig") if isinstance(cluster.get("resourcesVpcConfig"), dict) else {}
    parts = [
        _stringify_identifier(cluster.get("name")),
        f"status {_stringify_identifier(cluster.get('status'))}" if cluster.get("status") else "",
        f"version {_stringify_identifier(cluster.get('version'))}" if cluster.get("version") else "",
        _endpoint_access_label(vpc_config),
        f"vpc {_stringify_identifier(vpc_config.get('vpcId'))}" if vpc_config.get("vpcId") else "",
        (
            f"cluster security group {_stringify_identifier(vpc_config.get('clusterSecurityGroupId'))}"
            if vpc_config.get("clusterSecurityGroupId")
            else ""
        ),
    ]
    return f"{prefix} -> " + ", ".join(part for part in parts if part)


def _pipeline_summary(prefix: str, service: str, result: dict[str, Any], parameters: dict[str, Any]) -> str:
    if service != "codepipeline" or not isinstance(result.get("pipelineState"), dict):
        return ""
    state = result["pipelineState"]
    name = _stringify_identifier(state.get("pipelineName")) or _stringify_identifier(parameters.get("name"))
    stages = state.get("stageStates") if isinstance(state.get("stageStates"), list) else []
    stage_names = [
        _stringify_identifier(stage.get("stageName"))
        for stage in stages
        if isinstance(stage, dict) and _stringify_identifier(stage.get("stageName"))
    ]
    suffix = f", stages {', '.join(stage_names[:8])}" if stage_names else ""
    return f"{prefix} -> pipeline {name or 'unknown'} state, {len(stages)} stages{suffix}"


def _waf_summary(prefix: str, service: str, result: dict[str, Any]) -> str:
    if service != "wafv2":
        return ""
    if isinstance(result.get("WebACL"), dict):
        web_acl = result["WebACL"]
        rules = web_acl.get("Rules") if isinstance(web_acl.get("Rules"), list) else []
        return (
            f"{prefix} -> web acl {_stringify_identifier(web_acl.get('Name')) or 'unknown'}, "
            f"default action {json.dumps(web_acl.get('DefaultAction') or {}, default=str)}, rules {len(rules)}"
        )
    if isinstance(result.get("IPSet"), dict):
        ip_set = result["IPSet"]
        addresses = ip_set.get("Addresses") if isinstance(ip_set.get("Addresses"), list) else []
        name = _stringify_identifier(ip_set.get("Name")) or "unknown"
        return f"{prefix} -> ip set {name}, addresses {len(addresses)}"
    return ""


def _summarize_aws_read_operation(payload: dict[str, Any], parameters: dict[str, Any]) -> str:
    service = _stringify_identifier(payload.get("service") or parameters.get("service"))
    operation = _stringify_identifier(payload.get("operation") or parameters.get("operation"))
    prefix = " ".join(part for part in ("aws_read_operation", service, operation) if part)
    result = _inner_result(payload)
    summary = (
        _sts_summary(prefix, service, result)
        or _eks_summary(prefix, service, result)
        or _pipeline_summary(prefix, service, result, parameters)
        or _waf_summary(prefix, service, result)
    )
    if summary:
        return summary

    items = _items_from_known_payload(payload)
    if items:
        preview = ", ".join(dict.fromkeys(items[:8]))
        suffix = f" (showing {min(len(items), 8)} of {len(items)})" if len(items) > 8 else ""
        return f"{prefix or 'aws_read_operation'} -> {preview}{suffix}"

    if service or operation:
        return f"{prefix} -> succeeded"
    return ""


def summarize_tool_result(tool_name: str, result: Any, parameters: dict[str, Any] | None = None) -> str:
    payload = _payload(result)
    if not payload:
        return ""
    if tool_name == "aws_read_operation":
        return _summarize_aws_read_operation(payload, parameters or {})
    count = payload.get("count")
    items = _items_from_known_payload(payload)
    prefix = tool_name
    if isinstance(count, int):
        prefix = f"{tool_name}: {count}"
    if items:
        preview = ", ".join(dict.fromkeys(items[:8]))
        suffix = f" (showing {min(len(items), 8)} of {len(items)})" if len(items) > 8 else ""
        return f"{prefix} -> {preview}{suffix}"
    service = _stringify_identifier(payload.get("service"))
    operation = _stringify_identifier(payload.get("operation"))
    if service or operation:
        return f"{prefix} -> {' '.join(part for part in (service, operation) if part)} succeeded"
    compact = json.dumps(payload, default=str)[:220]
    return f"{prefix} -> {compact}"
