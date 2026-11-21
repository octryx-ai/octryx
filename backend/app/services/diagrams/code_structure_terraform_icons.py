"""Provider icon mapping for the Terraform infrastructure views.

``aws_*`` resource types map onto the AWS topology node-type vocabulary so the
renderer reuses the official aws4 shape aliases (``_NODE_SHAPE_ALIASES``) and
category fills. Azure (``azurerm_*``) and Google Cloud (``google_*``)
resources flow through the same pipeline today and render as neutral
provider-tagged boxes; to give them official shapes later, add
``_AZURERM_RESOURCE_NODE_TYPES`` / ``_GOOGLE_RESOURCE_NODE_TYPES`` tables plus
a per-provider style hook in ``node_visual`` — no other layer changes.
"""

from __future__ import annotations

from typing import Any

from .aws_topology_shapes import (
    _DEFAULT_ICON_FILL,
    _GENERIC_FALLBACK_SHAPE,
    _NODE_SHAPE_ALIASES,
    _NODE_TYPE_ICON_FILLS,
)

ICON_SIZE = 68
BOX_WIDTH = 150
BOX_HEIGHT = 56

# Neutral provider-tagged box styles for resources without an official shape
# set (Azure/GCP extension point: replace with per-provider shape tables).
PROVIDER_BOX_STROKES = {"azurerm": "#0078d4", "google": "#4285f4", "other": "#94a3b8"}
MODULE_STYLE = "rounded=1;whiteSpace=wrap;html=1;fontSize=10;fillColor=#e1d5e7;strokeColor=#9673a6;"

# aws_* resource types -> AWS topology node types (the keys of
# _NODE_SHAPE_ALIASES / _NODE_TYPE_ICON_FILLS in aws_topology_shapes).
_AWS_RESOURCE_NODE_TYPES = {
    "aws_vpc": "vpc",
    "aws_subnet": "subnet",
    "aws_security_group": "security_group",
    "aws_route_table": "route_table",
    "aws_internet_gateway": "internet_gateway",
    "aws_nat_gateway": "nat_gateway",
    "aws_lb": "load_balancer",
    "aws_alb": "load_balancer",
    "aws_elb": "load_balancer",
    "aws_lb_target_group": "target_group",
    "aws_alb_target_group": "target_group",
    "aws_eks_cluster": "eks_cluster",
    "aws_eks_node_group": "eks_nodegroup",
    "aws_autoscaling_group": "autoscaling_group",
    "aws_db_instance": "rds_instance",
    "aws_rds_cluster": "rds_cluster",
    "aws_rds_cluster_instance": "rds_instance",
    "aws_db_proxy": "rds_proxy",
    "aws_dynamodb_table": "dynamodb_table",
    "aws_lambda_function": "lambda_function",
    "aws_s3_bucket": "s3_bucket",
    "aws_codepipeline": "codepipeline",
    "aws_wafv2_web_acl": "waf_web_acl",
    "aws_waf_web_acl": "waf_web_acl",
    "aws_ecs_cluster": "ecs_cluster",
    "aws_ecs_service": "ecs_service",
    "aws_instance": "ec2_instance",
    "aws_api_gateway_rest_api": "api_gateway",
    "aws_apigatewayv2_api": "api_gateway",
    "aws_cloudfront_distribution": "cloudfront_distribution",
    "aws_route53_zone": "route53_zone",
    "aws_vpc_peering_connection": "vpc_peering",
    "aws_ec2_transit_gateway": "transit_gateway",
    "aws_vpc_endpoint": "vpc_endpoint",
    "aws_elasticache_cluster": "elasticache_cluster",
    "aws_elasticache_replication_group": "elasticache_cluster",
    "aws_redshift_cluster": "redshift_cluster",
    "aws_efs_file_system": "efs_file_system",
    "aws_ecr_repository": "ecr_repository",
    "aws_sqs_queue": "sqs_queue",
    "aws_sns_topic": "sns_topic",
    "aws_sfn_state_machine": "step_function",
    "aws_cloudwatch_event_bus": "eventbridge_bus",
    "aws_kinesis_stream": "kinesis_stream",
    "aws_msk_cluster": "msk_cluster",
    "aws_mq_broker": "mq_broker",
    "aws_secretsmanager_secret": "secrets_manager_secret",
    "aws_secretsmanager_secret_version": "secrets_manager_secret",
    "aws_kms_key": "kms_key",
    # Sub-resources and data-source plurals inherit their family's icon so
    # real repos do not degrade to the generic fallback.
    "aws_db_proxy_default_target_group": "rds_proxy",
    "aws_db_proxy_target": "rds_proxy",
    "aws_db_proxy_endpoint": "rds_proxy",
    "aws_security_group_rule": "security_group",
    "aws_iam_role": "iam_role",
    "aws_iam_user": "iam_role",
    "aws_iam_policy": "iam_role",
    "aws_iam_role_policy": "iam_role",
    "aws_iam_role_policy_attachment": "iam_role",
    "aws_iam_user_policy_attachment": "iam_role",
    "aws_iam_policy_document": "iam_role",
    "aws_iam_instance_profile": "iam_role",
    "aws_route53_record": "route53_zone",
    "aws_route53_resolver_rule": "route53_zone",
    "aws_route53_resolver_rule_association": "route53_zone",
    "aws_globalaccelerator_accelerator": "global_accelerator",
    "aws_globalaccelerator_listener": "global_accelerator",
    "aws_globalaccelerator_endpoint_group": "global_accelerator",
    "aws_codecommit_repository": "codecommit_repository",
    "aws_efs_mount_target": "efs_file_system",
    "aws_efs_access_point": "efs_file_system",
    "aws_subnets": "subnet",
    "aws_route_tables": "route_table",
    "aws_lb_listener": "load_balancer",
    "aws_lb_listener_rule": "load_balancer",
    "aws_sqs_queue_policy": "sqs_queue",
    "aws_acm_certificate": "acm_certificate",
    "aws_ssm_parameter": "ssm_parameter",
    "aws_caller_identity": "iam_role",
}

# Longest-prefix family fallback AFTER the exact table: every future
# sub-resource of a known service family inherits that family's icon
# instead of degrading to the generic resource icon. Ordered by prefix
# length at lookup time, so more specific families win (aws_vpc_endpoint
# before aws_vpc). aws_region stays generic on purpose - it is metadata,
# not a service.
_AWS_FAMILY_PREFIXES: dict[str, str] = {
    "aws_iam_": "iam_role",
    "aws_s3_": "s3_bucket",
    "aws_route53_": "route53_zone",
    "aws_db_proxy": "rds_proxy",
    "aws_rds_": "rds_cluster",
    "aws_db_": "rds_instance",
    "aws_lambda_": "lambda_function",
    "aws_sqs_": "sqs_queue",
    "aws_sns_": "sns_topic",
    "aws_ec2_transit_gateway": "transit_gateway",
    "aws_vpc_endpoint": "vpc_endpoint",
    "aws_vpc_peering": "vpc_peering",
    "aws_vpc": "vpc",
    "aws_subnet": "subnet",
    "aws_route_table": "route_table",
    "aws_security_group": "security_group",
    "aws_lb_": "load_balancer",
    "aws_alb_": "load_balancer",
    "aws_elb": "load_balancer",
    "aws_eks_": "eks_cluster",
    "aws_ecs_": "ecs_cluster",
    "aws_ecr_": "ecr_repository",
    "aws_efs_": "efs_file_system",
    "aws_cloudfront_": "cloudfront_distribution",
    "aws_api_gateway_": "api_gateway",
    "aws_apigatewayv2_": "api_gateway",
    "aws_globalaccelerator_": "global_accelerator",
    "aws_codecommit_": "codecommit_repository",
    "aws_codepipeline": "codepipeline",
    "aws_secretsmanager_": "secrets_manager_secret",
    "aws_kms_": "kms_key",
    "aws_dynamodb_": "dynamodb_table",
    "aws_elasticache_": "elasticache_cluster",
    "aws_kinesis_": "kinesis_stream",
    "aws_cloudwatch_event": "eventbridge_bus",
    "aws_sfn_": "step_function",
    "aws_wafv2_": "waf_web_acl",
    "aws_waf": "waf_web_acl",
    "aws_acm_": "acm_certificate",
    "aws_ssm_": "ssm_parameter",
    "aws_autoscaling_": "autoscaling_group",
    "aws_instance": "ec2_instance",
    "aws_nat_gateway": "nat_gateway",
    "aws_internet_gateway": "internet_gateway",
    "aws_redshift_": "redshift_cluster",
    "aws_msk_": "msk_cluster",
    "aws_mq_": "mq_broker",
}


def aws_node_type(resource_type: str) -> str:
    exact = _AWS_RESOURCE_NODE_TYPES.get(resource_type, "")
    if exact:
        return exact
    for prefix in sorted(_AWS_FAMILY_PREFIXES, key=len, reverse=True):
        if resource_type.startswith(prefix):
            return _AWS_FAMILY_PREFIXES[prefix]
    return ""


def short_name(label: str) -> str:
    return label.rsplit(".", 1)[-1] if "." in label else label


def node_visual(node: dict[str, Any]) -> tuple[str, str, int, int]:
    """Return (label, style, width, height) — official aws4 icons for mapped
    aws_* types, the existing generic-resource fallback for unmapped aws_*
    types, neutral provider-tagged boxes otherwise (Azure/GCP hook point)."""
    attributes = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
    kind = str(node.get("type") or "")
    label = str(node.get("label") or "")
    resource_type = str(attributes.get("resource_type") or "")
    provider = str(attributes.get("provider") or "")
    if kind == "module":
        return f"{short_name(label)}\nmodule", MODULE_STYLE, BOX_WIDTH, BOX_HEIGHT
    display = f"{short_name(label)}\n{resource_type}" if resource_type else label
    if kind == "data" and resource_type:
        display = f"{short_name(label)}\ndata.{resource_type}"
    if provider == "aws":
        node_type = aws_node_type(resource_type)
        aliases = _NODE_SHAPE_ALIASES.get(node_type, ())
        shape = aliases[0] if aliases else _GENERIC_FALLBACK_SHAPE
        fill = _NODE_TYPE_ICON_FILLS.get(node_type, _DEFAULT_ICON_FILL)
        style = (
            f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{shape};"
            "verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
            f"fontSize=9;fontColor=#111827;aspect=fixed;fillColor={fill};"
            "strokeColor=#ffffff;whiteSpace=wrap;"
        )
        return display, style, ICON_SIZE, ICON_SIZE
    stroke = PROVIDER_BOX_STROKES.get(provider, PROVIDER_BOX_STROKES["other"])
    style = f"rounded=1;whiteSpace=wrap;html=1;fontSize=10;fillColor=#ffffff;strokeColor={stroke};"
    return display, style, BOX_WIDTH, BOX_HEIGHT
