"""AWS service ordering, icon colours and draw.io shape lookup for topology nodes."""

from __future__ import annotations

from typing import Any

_SERVICE_ORDER = ("sts", "wafv2", "elbv2", "ec2", "eks", "rds", "dynamodb", "lambda", "s3", "codepipeline")
_SERVICE_LABELS = {
    "sts": "AWS Account",
    "wafv2": "WAF",
    "elbv2": "Load Balancing",
    "ec2": "Network / EC2",
    "eks": "EKS",
    "rds": "RDS",
    "dynamodb": "DynamoDB",
    "lambda": "Lambda",
    "s3": "S3",
    "codepipeline": "CodePipeline",
}
# AWS architecture-icon category fill colors (2025 icon set): networking purple,
# compute orange, database/dev-tools pink, storage green, security red, ML teal.
_DEFAULT_ICON_FILL = "#ED7100"
_NODE_TYPE_ICON_FILLS = {
    "vpc": "#8C4FFF",
    "subnet": "#8C4FFF",
    "internet_gateway": "#8C4FFF",
    "nat_gateway": "#8C4FFF",
    "route_table": "#8C4FFF",
    "load_balancer": "#8C4FFF",
    "target_group": "#8C4FFF",
    "eks_cluster": "#ED7100",
    "eks_nodegroup": "#ED7100",
    "autoscaling_group": "#ED7100",
    "lambda_function": "#ED7100",
    "rds_instance": "#C925D1",
    "dynamodb_table": "#C925D1",
    "s3_bucket": "#7AA116",
    "codepipeline": "#C925D1",
    "waf_web_acl": "#DD344C",
    "security_group": "#DD344C",
    "bedrock_model": "#01A88D",
    # Compute (orange)
    "ecs_cluster": "#ED7100",
    "ecs_service": "#ED7100",
    "ec2_instance": "#ED7100",
    # Networking / ingress (purple)
    "api_gateway": "#8C4FFF",
    "cloudfront_distribution": "#8C4FFF",
    "route53_zone": "#8C4FFF",
    "vpc_peering": "#8C4FFF",
    "transit_gateway": "#8C4FFF",
    "vpc_endpoint": "#8C4FFF",
    # Database (magenta)
    "elasticache_cluster": "#C925D1",
    "rds_proxy": "#C925D1",
    "rds_cluster": "#C925D1",
    "redshift_cluster": "#C925D1",
    # Storage (green)
    "efs_file_system": "#7AA116",
    "ecr_repository": "#7AA116",
    # Application integration (pink)
    "sqs_queue": "#E7157B",
    "sns_topic": "#E7157B",
    "step_function": "#E7157B",
    "eventbridge_bus": "#E7157B",
    "kinesis_stream": "#E7157B",
    "msk_cluster": "#E7157B",
    "mq_broker": "#E7157B",
    # Security (red)
    "secrets_manager_secret": "#DD344C",
    "kms_key": "#DD344C",
    "iam_role": "#DD344C",
    "acm_certificate": "#DD344C",
    # Management (pink)
    "ssm_parameter": "#E7157B",
    # Networking (purple)
    "global_accelerator": "#8C4FFF",
    # Developer tools (magenta-purple)
    "codecommit_repository": "#C925D1",
}
_NODE_SHAPE_ALIASES = {
    "vpc": ("vpc",),
    "subnet": ("group_subnet",),
    "security_group": ("security_group",),
    "route_table": ("route_table",),
    "internet_gateway": ("internet_gateway",),
    "nat_gateway": ("nat_gateway",),
    "load_balancer": ("application_load_balancer", "elastic_load_balancing"),
    # aws4 has no dedicated target-group resource icon.
    "target_group": ("elastic_load_balancing",),
    "eks_cluster": ("eks",),
    "eks_nodegroup": ("ec2", "auto_scaling"),
    "autoscaling_group": ("auto_scaling", "ec2"),
    "rds_instance": ("rds",),
    "dynamodb_table": ("dynamodb", "dynamodb_table"),
    "lambda_function": ("lambda",),
    "s3_bucket": ("s3",),
    "codepipeline": ("codepipeline",),
    "waf_web_acl": ("waf",),
    "bedrock_model": ("bedrock",),
    "ecs_cluster": ("ecs",),
    "ecs_service": ("fargate", "ecs"),
    "ec2_instance": ("ec2",),
    "api_gateway": ("api_gateway",),
    "cloudfront_distribution": ("cloudfront",),
    "route53_zone": ("route_53",),
    "vpc_peering": ("vpc_peering", "vpc"),
    "transit_gateway": ("transit_gateway", "vpc"),
    "vpc_endpoint": ("endpoints", "vpc"),
    "elasticache_cluster": ("elasticache",),
    "rds_proxy": ("rds_proxy", "rds"),
    "rds_cluster": ("rds",),
    "redshift_cluster": ("redshift",),
    "efs_file_system": ("elastic_file_system",),
    "ecr_repository": ("ecr",),
    "sqs_queue": ("sqs",),
    "sns_topic": ("sns",),
    "step_function": ("step_functions",),
    "eventbridge_bus": ("eventbridge",),
    "kinesis_stream": ("kinesis",),
    "msk_cluster": ("managed_streaming_for_kafka",),
    "mq_broker": ("mq",),
    "secrets_manager_secret": ("secrets_manager",),
    "kms_key": ("key_management_service",),
    "iam_role": ("identity_and_access_management",),
    "global_accelerator": ("global_accelerator",),
    "codecommit_repository": ("codecommit",),
    "acm_certificate": ("certificate_manager",),
    "ssm_parameter": ("systems_manager",),
}
# Fallback shape for any discovered resource type without a dedicated alias, so
# newly-covered services render as a generic AWS resource icon rather than a
# plain box.
_GENERIC_FALLBACK_SHAPE = "general"
_GENERIC_ONLY_NODE_TYPES = {"aws_account", "cidr"}


def _matched_shape_lookup(shape_library_result: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for item in shape_library_result.get("matched_shapes") or []:
        if not isinstance(item, dict):
            continue
        requested = str(item.get("requested") or "").strip().lower()
        shape = str(item.get("shape") or "").strip()
        if requested and shape:
            lookup[requested] = shape
    return lookup


def _node_shape(node_type: str, shape_lookup: dict[str, str]) -> str:
    if node_type in _GENERIC_ONLY_NODE_TYPES:
        return ""
    for alias in _NODE_SHAPE_ALIASES.get(node_type, ()):
        if alias in shape_lookup:
            return shape_lookup[alias]
    aliases = _NODE_SHAPE_ALIASES.get(node_type, ())
    if aliases:
        return aliases[0]
    # Any resource type the connector emits but the renderer has no alias for
    # still gets a generic AWS resource icon instead of a plain box.
    return _GENERIC_FALLBACK_SHAPE


def _service_rank(service: str) -> int:
    try:
        return _SERVICE_ORDER.index(service)
    except ValueError:
        return len(_SERVICE_ORDER)


def _service_label(service: str) -> str:
    if service in _SERVICE_LABELS:
        return _SERVICE_LABELS[service]
    return service.replace("_", " ").upper() if len(service) <= 4 else service.replace("_", " ").title()

