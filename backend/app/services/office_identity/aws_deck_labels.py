"""Readable names for AWS resource types — and the rule that guards them."""

from __future__ import annotations

import re
from typing import Any

#: ``node type -> (singular, plural)``. Only the types the theme catalog knows
#: appear here; both files are edited together when a theme gains a type.
NODE_TYPE_LABELS: dict[str, tuple[str, str]] = {
    # network
    "vpc": ("VPC", "VPCs"),
    "subnet": ("subnet", "subnets"),
    "route_table": ("route table", "route tables"),
    "internet_gateway": ("internet gateway", "internet gateways"),
    "nat_gateway": ("NAT gateway", "NAT gateways"),
    "transit_gateway": ("transit gateway", "transit gateways"),
    "vpc_endpoint": ("VPC endpoint", "VPC endpoints"),
    "vpc_peering_connection": ("VPC peering connection", "VPC peering connections"),
    "cidr": ("CIDR block", "CIDR blocks"),
    "availability_zone": ("availability zone", "availability zones"),
    "load_balancer": ("load balancer", "load balancers"),
    "target_group": ("target group", "target groups"),
    "hosted_zone": ("hosted zone", "hosted zones"),
    "dns_record": ("DNS record", "DNS records"),
    # compute
    "ec2_instance": ("EC2 instance", "EC2 instances"),
    "auto_scaling_group": ("Auto Scaling group", "Auto Scaling groups"),
    "launch_template": ("launch template", "launch templates"),
    "eks_cluster": ("EKS cluster", "EKS clusters"),
    "eks_nodegroup": ("EKS node group", "EKS node groups"),
    "ecs_cluster": ("ECS cluster", "ECS clusters"),
    "ecs_service": ("ECS service", "ECS services"),
    "ecs_task_definition": ("ECS task definition", "ECS task definitions"),
    "lambda_function": ("Lambda function", "Lambda functions"),
    "batch_job_queue": ("Batch job queue", "Batch job queues"),
    "app_runner_service": ("App Runner service", "App Runner services"),
    # data
    "rds_instance": ("RDS instance", "RDS instances"),
    "rds_cluster": ("RDS cluster", "RDS clusters"),
    "dynamodb_table": ("DynamoDB table", "DynamoDB tables"),
    "s3_bucket": ("S3 bucket", "S3 buckets"),
    "elasticache_cluster": ("ElastiCache cluster", "ElastiCache clusters"),
    "efs_file_system": ("EFS file system", "EFS file systems"),
    "redshift_cluster": ("Redshift cluster", "Redshift clusters"),
    "opensearch_domain": ("OpenSearch domain", "OpenSearch domains"),
    "ebs_volume": ("EBS volume", "EBS volumes"),
    "backup_vault": ("backup vault", "backup vaults"),
    # identity and security
    "security_group": ("security group", "security groups"),
    "network_acl": ("network ACL", "network ACLs"),
    "iam_role": ("IAM role", "IAM roles"),
    "iam_user": ("IAM user", "IAM users"),
    "iam_group": ("IAM group", "IAM groups"),
    "iam_policy": ("IAM policy", "IAM policies"),
    "kms_key": ("KMS key", "KMS keys"),
    "secret": ("secret", "secrets"),
    "waf_web_acl": ("WAF web ACL", "WAF web ACLs"),
    "acm_certificate": ("ACM certificate", "ACM certificates"),
    "guardduty_detector": ("GuardDuty detector", "GuardDuty detectors"),
    # integration and operations
    "sns_topic": ("SNS topic", "SNS topics"),
    "sqs_queue": ("SQS queue", "SQS queues"),
    "eventbridge_rule": ("EventBridge rule", "EventBridge rules"),
    "api_gateway": ("API gateway", "API gateways"),
    "cloudfront_distribution": ("CloudFront distribution", "CloudFront distributions"),
    "step_function": ("Step Functions state machine", "Step Functions state machines"),
    "log_group": ("log group", "log groups"),
    "cloudwatch_alarm": ("CloudWatch alarm", "CloudWatch alarms"),
    "codepipeline": ("CodePipeline pipeline", "CodePipeline pipelines"),
    "codebuild_project": ("CodeBuild project", "CodeBuild projects"),
}


def resource_phrase(node_type: str, count: int) -> str:
    label = NODE_TYPE_LABELS.get(node_type)
    if label is None:
        noun = "resource" if count == 1 else "resources"
        return f"{count} {noun} of type \"{node_type}\""
    return f"{count} {label[0] if count == 1 else label[1]}"


# ---------------------------------------------------------------------------
# the honesty guard
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d+")

#: Nesting deeper than this in a snapshot is not walked; the guard stays bounded.
_MAX_DEPTH = 12


def numbers_in(text: str) -> set[int]:
    return {int(match) for match in _NUMBER.findall(text)}


def permitted_numbers(snapshot: Any, _depth: int = 0) -> set[int]:
    found: set[int] = set()
    if _depth > _MAX_DEPTH:
        return found
    if isinstance(snapshot, bool):
        return found
    if isinstance(snapshot, int):
        return {snapshot}
    if isinstance(snapshot, float):
        return {int(snapshot)} if snapshot.is_integer() else set()
    if isinstance(snapshot, str):
        return numbers_in(snapshot)
    if isinstance(snapshot, dict):
        found.add(len(snapshot))
        for key, value in snapshot.items():
            found |= numbers_in(str(key))
            found |= permitted_numbers(value, _depth + 1)
        return found
    if isinstance(snapshot, (list, tuple)):
        found.add(len(snapshot))
        for item in snapshot:
            found |= permitted_numbers(item, _depth + 1)
        return found
    return found


__all__ = [
    "NODE_TYPE_LABELS",
    "numbers_in",
    "permitted_numbers",
    "resource_phrase",
]
