"""Extended AWS topology collectors for broader service coverage.

Each collector is read-only and routed through ``safe_aws_call`` so a missing
IAM permission or a service that is simply not used in an account degrades to a
warning instead of failing the snapshot. This is what lets one connector read
"whatever is present" across many different accounts.

VPC-bound resources emit ``runs_in``/``uses_subnet``/``uses_security_group``
edges so the renderer nests them into the right subnet tier; regional/global
resources (API Gateway, CloudFront, Route 53, SQS, SNS, …) carry no VPC edge
and land in the regional-services group.
"""

from __future__ import annotations

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, safe_aws_call
from .aws_topology_node_links import add_simple_node
from .common import _string


async def discover_apigateway(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    rest = (await safe_aws_call(context, builder, "apigateway", ["get-rest-apis"])) or {}
    for api in (rest.get("items") or [])[:max_items]:
        name = _string(api.get("name")) or _string(api.get("id"))
        if not name:
            continue
        add_simple_node(
            builder, node_type="api_gateway", identifier=_string(api.get("id")), label=name,
            service="apigateway", region=region, arn=None, operation="get-rest-apis",
            attributes={"api_type": "REST", "endpoint": (api.get("endpointConfiguration") or {}).get("types")},
        )
    http = (await safe_aws_call(context, builder, "apigatewayv2", ["get-apis"])) or {}
    for api in (http.get("Items") or [])[:max_items]:
        name = _string(api.get("Name")) or _string(api.get("ApiId"))
        if not name:
            continue
        add_simple_node(
            builder, node_type="api_gateway", identifier=_string(api.get("ApiId")), label=name,
            service="apigatewayv2", region=region, arn=None, operation="get-apis",
            attributes={"api_type": _string(api.get("ProtocolType")) or "HTTP"},
        )


async def discover_cloudfront(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "cloudfront", ["list-distributions"])) or {}
    for dist in ((data.get("DistributionList") or {}).get("Items") or [])[:max_items]:
        did = _string(dist.get("Id"))
        if not did:
            continue
        aliases = (dist.get("Aliases") or {}).get("Items") or []
        origin_domains = [
            _string(origin.get("DomainName"))
            for origin in ((dist.get("Origins") or {}).get("Items") or [])
            if _string(origin.get("DomainName"))
        ]
        add_simple_node(
            builder, node_type="cloudfront_distribution", identifier=did,
            label=aliases[0] if aliases else did,
            service="cloudfront", region="global", arn=_string(dist.get("ARN")) or None,
            operation="list-distributions",
            attributes={"status": dist.get("Status"), "enabled": dist.get("Enabled"),
                        "domain": dist.get("DomainName"), "origin_domains": origin_domains[:8]},
        )


async def discover_route53(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "route53", ["list-hosted-zones"])) or {}
    for zone in (data.get("HostedZones") or [])[:max_items]:
        name = _string(zone.get("Name")).rstrip(".")
        if not name:
            continue
        add_simple_node(
            builder, node_type="route53_zone", identifier=_string(zone.get("Id")), label=name,
            service="route53", region="global", arn=None, operation="list-hosted-zones",
            attributes={"private": (zone.get("Config") or {}).get("PrivateZone"),
                        "record_count": zone.get("ResourceRecordSetCount"),
                        "hosted_zone_id": _string(zone.get("Id")).rsplit("/", 1)[-1]},
        )


async def discover_sqs(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "sqs", ["list-queues"])) or {}
    for url in (data.get("QueueUrls") or [])[:max_items]:
        name = _string(url).rsplit("/", 1)[-1]
        if not name:
            continue
        add_simple_node(
            builder, node_type="sqs_queue", identifier=_string(url), label=name,
            service="sqs", region=region, arn=None, operation="list-queues",
            attributes={"fifo": name.endswith(".fifo")},
        )


async def discover_sns(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "sns", ["list-topics"])) or {}
    for topic in (data.get("Topics") or [])[:max_items]:
        arn = _string(topic.get("TopicArn"))
        if not arn:
            continue
        add_simple_node(
            builder, node_type="sns_topic", identifier=arn, label=arn.rsplit(":", 1)[-1],
            service="sns", region=region, arn=arn, operation="list-topics",
            attributes={"fifo": arn.endswith(".fifo")},
        )


async def discover_ecr(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "ecr", ["describe-repositories"])) or {}
    for repo in (data.get("repositories") or [])[:max_items]:
        name = _string(repo.get("repositoryName"))
        if not name:
            continue
        add_simple_node(
            builder, node_type="ecr_repository", identifier=name,
            label=name, service="ecr", region=region,
            arn=_string(repo.get("repositoryArn")) or None, operation="describe-repositories",
            attributes={"tag_mutability": repo.get("imageTagMutability")},
        )


async def discover_secrets(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "secretsmanager", ["list-secrets"])) or {}
    for secret in (data.get("SecretList") or [])[:max_items]:
        name = _string(secret.get("Name"))
        if not name:
            continue
        add_simple_node(
            builder, node_type="secrets_manager_secret", identifier=name, label=name,
            service="secretsmanager", region=region, arn=_string(secret.get("ARN")) or None,
            operation="list-secrets", attributes={},
        )


async def discover_stepfunctions(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "stepfunctions", ["list-state-machines"])) or {}
    for machine in (data.get("stateMachines") or [])[:max_items]:
        name = _string(machine.get("name"))
        if not name:
            continue
        add_simple_node(
            builder, node_type="step_function", identifier=name, label=name,
            service="stepfunctions", region=region, arn=_string(machine.get("stateMachineArn")) or None,
            operation="list-state-machines", attributes={"type": machine.get("type")},
        )


async def discover_eventbridge(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "events", ["list-event-buses"])) or {}
    for bus in (data.get("EventBuses") or [])[:max_items]:
        name = _string(bus.get("Name"))
        # skip the noisy always-present default bus
        if not name or name == "default":
            continue
        add_simple_node(
            builder, node_type="eventbridge_bus", identifier=name, label=name,
            service="eventbridge", region=region, arn=_string(bus.get("Arn")) or None,
            operation="list-event-buses", attributes={},
        )
