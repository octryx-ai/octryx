"""Per-region dispatch of the AWS topology service collectors."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder
from .aws_topology_eks import discover_eks
from .aws_topology_load_balancers import discover_elbv2
from .aws_topology_network import discover_ec2_network
from .aws_topology_rds import discover_rds
from .aws_topology_services import (
    discover_bedrock,
    discover_codepipeline,
    discover_dynamodb,
    discover_lambda,
    discover_s3,
    discover_wafv2,
)
from .aws_topology_services_extended import (
    discover_apigateway,
    discover_cloudfront,
    discover_ecr,
    discover_eventbridge,
    discover_route53,
    discover_secrets,
    discover_sns,
    discover_sqs,
    discover_stepfunctions,
)
from .aws_topology_vpc_services import (
    discover_ec2_instances,
    discover_ecs,
    discover_efs,
    discover_elasticache,
    discover_networking_extras,
)
from .common import _string

# A fixed discovery order keeps node and edge order stable across snapshots.
_REGION_DISCOVERERS = (
    ("ec2", discover_ec2_network),
    ("elbv2", discover_elbv2),
    ("eks", discover_eks),
    ("rds", discover_rds),
    ("dynamodb", discover_dynamodb),
    ("codepipeline", discover_codepipeline),
    ("wafv2", discover_wafv2),
    ("lambda", discover_lambda),
    ("s3", discover_s3),
    ("bedrock", discover_bedrock),
    ("ecs", discover_ecs),
    ("apigateway", discover_apigateway),
    ("cloudfront", discover_cloudfront),
    ("route53", discover_route53),
    ("elasticache", discover_elasticache),
    ("efs", discover_efs),
    ("ecr", discover_ecr),
    ("sqs", discover_sqs),
    ("sns", discover_sns),
    ("secretsmanager", discover_secrets),
    ("stepfunctions", discover_stepfunctions),
    ("eventbridge", discover_eventbridge),
    ("ec2-instances", discover_ec2_instances),
    ("networking", discover_networking_extras),
)


async def discover_region_services(
    context: ToolContext,
    builder: TopologyBuilder,
    services: set[str],
    *,
    region: str,
    max_items: int,
    params: dict[str, Any],
) -> None:
    for service, discover in _REGION_DISCOVERERS:
        if service not in services:
            continue
        if service == "wafv2":
            await discover(context, builder, region=region, max_items=max_items, scope=_waf_scope(params))
        else:
            await discover(context, builder, region=region, max_items=max_items)


def _waf_scope(params: dict[str, Any]) -> str:
    scope = _string(params.get("waf_scope")).upper() or "REGIONAL"
    return scope if scope in {"REGIONAL", "CLOUDFRONT"} else "REGIONAL"
