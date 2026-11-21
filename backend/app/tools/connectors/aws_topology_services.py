"""Service-specific AWS topology collectors."""

from __future__ import annotations

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, evidence, node_id, safe_aws_call
from .common import _string


async def discover_dynamodb(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "dynamodb", ["list-tables"])) or {}
    for table_name in (data.get("TableNames") or [])[:max_items]:
        name = _string(table_name)
        if not name:
            continue
        detail = (
            await safe_aws_call(
                context,
                builder,
                "dynamodb",
                ["describe-table", "--table-name", name],
            )
        ) or {}
        table = detail.get("Table") or {}
        arn = _string(table.get("TableArn")) or None
        billing = table.get("BillingModeSummary") or {}
        stream_spec = table.get("StreamSpecification") or {}
        builder.add_node(
            node_id("dynamodb_table", arn or name),
            node_type="dynamodb_table",
            label=name,
            service="dynamodb",
            region=region,
            arn=arn,
            attributes={
                "status": table.get("TableStatus"),
                "billing_mode": billing.get("BillingMode"),
                "item_count": table.get("ItemCount"),
                "table_size_bytes": table.get("TableSizeBytes"),
                "stream_enabled": stream_spec.get("StreamEnabled"),
                "stream_view_type": stream_spec.get("StreamViewType"),
                "deletion_protection_enabled": table.get("DeletionProtectionEnabled"),
            },
            evidence_items=[evidence("dynamodb", "describe-table", f"Table[{name}]")],
        )


async def discover_codepipeline(
    context: ToolContext,
    builder: TopologyBuilder,
    *,
    region: str,
    max_items: int,
) -> None:
    data = (await safe_aws_call(context, builder, "codepipeline", ["list-pipelines"])) or {}
    for item in (data.get("pipelines") or [])[:max_items]:
        name = _string(item.get("name"))
        if not name:
            continue
        builder.add_node(
            node_id("codepipeline", name),
            node_type="codepipeline",
            label=name,
            service="codepipeline",
            region=region,
            attributes={"version": item.get("version"), "created": item.get("created"), "updated": item.get("updated")},
            evidence_items=[evidence("codepipeline", "list-pipelines", f"pipelines[{name}]")],
        )


async def discover_wafv2(
    context: ToolContext,
    builder: TopologyBuilder,
    *,
    region: str,
    max_items: int,
    scope: str,
) -> None:
    data = (await safe_aws_call(context, builder, "wafv2", ["list-web-acls", "--scope", scope])) or {}
    for item in (data.get("WebACLs") or [])[:max_items]:
        name = _string(item.get("Name"))
        identifier = _string(item.get("Id") or item.get("ARN") or name)
        if not identifier:
            continue
        builder.add_node(
            node_id("waf_web_acl", item.get("ARN") or identifier),
            node_type="waf_web_acl",
            label=name or identifier,
            service="wafv2",
            region=region,
            arn=_string(item.get("ARN")) or None,
            attributes={"id": item.get("Id"), "lock_token": item.get("LockToken"), "scope": scope},
            evidence_items=[evidence("wafv2", "list-web-acls", f"WebACLs[{name or identifier}]")],
        )
        arn = _string(item.get("ARN"))
        if arn:
            await _link_waf_resources(context, builder, web_acl_arn=arn, web_acl_node_id=node_id("waf_web_acl", arn))


async def _link_waf_resources(
    context: ToolContext,
    builder: TopologyBuilder,
    *,
    web_acl_arn: str,
    web_acl_node_id: str,
) -> None:
    data = (
        await safe_aws_call(
            context,
            builder,
            "wafv2",
            [
                "list-resources-for-web-acl",
                "--web-acl-arn",
                web_acl_arn,
                "--resource-type",
                "APPLICATION_LOAD_BALANCER",
            ],
        )
    ) or {}
    for resource_arn in data.get("ResourceArns") or []:
        arn = _string(resource_arn)
        if not arn:
            continue
        builder.add_edge(
            web_acl_node_id,
            node_id("load_balancer", arn),
            "protects",
            service="wafv2",
            evidence_items=[evidence("wafv2", "list-resources-for-web-acl", f"ResourceArns[{arn}]")],
        )


async def discover_lambda(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "lambda", ["list-functions"])) or {}
    for item in (data.get("Functions") or [])[:max_items]:
        name = _string(item.get("FunctionName"))
        arn = _string(item.get("FunctionArn")) or None
        if not name:
            continue
        item_id = node_id("lambda_function", arn or name)
        vpc_config = item.get("VpcConfig") or {}
        builder.add_node(
            item_id,
            node_type="lambda_function",
            label=name,
            service="lambda",
            region=region,
            arn=arn,
            attributes={
                "runtime": item.get("Runtime"),
                "handler": item.get("Handler"),
                "state": item.get("State"),
                "vpc_id": vpc_config.get("VpcId"),
            },
            evidence_items=[evidence("lambda", "list-functions", f"Functions[{name}]")],
        )
        link_vpc_config(builder, item_id, "lambda", "list-functions", f"Functions[{name}]", vpc_config)


async def discover_s3(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "s3", ["list-buckets"])) or {}
    for item in (data.get("Buckets") or [])[:max_items]:
        name = _string(item.get("Name"))
        if not name:
            continue
        builder.add_node(
            node_id("s3_bucket", name),
            node_type="s3_bucket",
            label=name,
            service="s3",
            region=region,
            attributes={"creation_date": item.get("CreationDate")},
            evidence_items=[evidence("s3", "list-buckets", f"Buckets[{name}]")],
        )


async def discover_bedrock(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "bedrock", ["list-foundation-models"])) or {}
    for item in (data.get("modelSummaries") or [])[:max_items]:
        model_id = _string(item.get("modelId"))
        if not model_id:
            continue
        builder.add_node(
            node_id("bedrock_model", model_id),
            node_type="bedrock_model",
            label=_string(item.get("modelName")) or model_id,
            service="bedrock",
            region=region,
            attributes={
                "provider_name": item.get("providerName"),
                "input_modalities": item.get("inputModalities"),
                "output_modalities": item.get("outputModalities"),
                "streaming": item.get("responseStreamingSupported"),
            },
            evidence_items=[evidence("bedrock", "list-foundation-models", f"modelSummaries[{model_id}]")],
        )


def link_vpc_config(
    builder: TopologyBuilder,
    item_id: str,
    service: str,
    operation: str,
    path_prefix: str,
    vpc_config: dict,
) -> None:
    vpc_id = _string(vpc_config.get("vpcId") or vpc_config.get("VpcId"))
    if vpc_id:
        builder.add_edge(
            item_id,
            node_id("vpc", vpc_id),
            "runs_in",
            service=service,
            evidence_items=[evidence(service, operation, f"{path_prefix}.VpcConfig")],
        )
    for subnet_id in vpc_config.get("subnetIds") or vpc_config.get("SubnetIds") or []:
        builder.add_edge(
            item_id,
            node_id("subnet", subnet_id),
            "uses_subnet",
            service=service,
            evidence_items=[evidence(service, operation, f"{path_prefix}.SubnetIds")],
        )
    for group_id in vpc_config.get("securityGroupIds") or vpc_config.get("SecurityGroupIds") or []:
        builder.add_edge(
            item_id,
            node_id("security_group", group_id),
            "uses_security_group",
            service=service,
            evidence_items=[evidence(service, operation, f"{path_prefix}.SecurityGroupIds")],
        )
