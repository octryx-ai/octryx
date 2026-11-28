"""The closed theme catalog of the AWS deck planner."""

from __future__ import annotations

#: Closed catalog: node type -> slide theme. Types outside it are not guessed
#: into a theme, they land on the "further resource types" slide together with
#: an explicit decision marker.
THEME_CATALOG: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Network foundation",
        (
            "vpc",
            "subnet",
            "route_table",
            "internet_gateway",
            "nat_gateway",
            "transit_gateway",
            "vpc_endpoint",
            "vpc_peering_connection",
            "cidr",
            "availability_zone",
            "load_balancer",
            "target_group",
            "hosted_zone",
            "dns_record",
        ),
    ),
    (
        "Compute and runtime",
        (
            "ec2_instance",
            "auto_scaling_group",
            "launch_template",
            "eks_cluster",
            "eks_nodegroup",
            "ecs_cluster",
            "ecs_service",
            "ecs_task_definition",
            "lambda_function",
            "batch_job_queue",
            "app_runner_service",
        ),
    ),
    (
        "Data and storage",
        (
            "rds_instance",
            "rds_cluster",
            "dynamodb_table",
            "s3_bucket",
            "elasticache_cluster",
            "efs_file_system",
            "redshift_cluster",
            "opensearch_domain",
            "ebs_volume",
            "backup_vault",
        ),
    ),
    (
        "Identity and security",
        (
            "security_group",
            "network_acl",
            "iam_role",
            "iam_user",
            "iam_group",
            "iam_policy",
            "kms_key",
            "secret",
            "waf_web_acl",
            "acm_certificate",
            "guardduty_detector",
        ),
    ),
    (
        "Integration and operations",
        (
            "sns_topic",
            "sqs_queue",
            "eventbridge_rule",
            "api_gateway",
            "cloudfront_distribution",
            "step_function",
            "log_group",
            "cloudwatch_alarm",
            "codepipeline",
            "codebuild_project",
        ),
    ),
)

#: Tail bucket for node types the catalog does not know.
OTHER_THEME = "Further recorded resource types"

CATALOGUED_TYPES = frozenset(node_type for _, types in THEME_CATALOG for node_type in types)


def theme_buckets(node_counts: dict[str, int]) -> list[tuple[str, list[tuple[str, int]]]]:
    buckets: list[tuple[str, list[tuple[str, int]]]] = []
    for theme, types in THEME_CATALOG:
        found = [(node_type, node_counts[node_type]) for node_type in types if node_type in node_counts]
        found.sort(key=lambda item: (-item[1], item[0]))
        if found:
            buckets.append((theme, found))
    unknown = [(name, count) for name, count in node_counts.items() if name not in CATALOGUED_TYPES]
    unknown.sort(key=lambda item: (-item[1], item[0]))
    if unknown:
        buckets.append((OTHER_THEME, unknown))
    return buckets


# ---------------------------------------------------------------------------
# knowledge-fact → theme routing (closed vocabulary, no fuzzy score, no model)
# ---------------------------------------------------------------------------

#: Theme name (as ``THEME_CATALOG`` states it) -> the closed topic key shared
#: with the icon vocabulary. The tail bucket has no topic key: it is a
#: catch-all, so no fact should be routed there.
THEME_TOPIC_KEYS: dict[str, str] = {
    "Network foundation": "network",
    "Compute and runtime": "compute",
    "Data and storage": "data",
    "Identity and security": "security",
    "Integration and operations": "integration",
}

#: Topic key -> the closed set of exact lower-case tokens that mark a knowledge
#: fact as belonging to that theme. Deliberately distinctive and technical: a
#: generic word ("load") would misroute, so it is left out. A fact is attached
#: to a theme only when its tokens hit **exactly one** of these sets — an
#: ambiguous fact keeps its place on the "Domain context" slide rather than
#: being forced onto a theme it only half belongs to.
KNOWLEDGE_TOPIC_KEYWORDS: dict[str, frozenset[str]] = {
    "network": frozenset(
        {
            "network", "networks", "vpc", "vpcs", "subnet", "subnets",
            "gateway", "gateways", "routing", "route", "load", "balancer",
            "loadbalancer", "cidr", "dns", "availability", "zone", "zones",
            "transit", "peering", "connectivity",
        }
    ),
    "compute": frozenset(
        {
            "ec2", "instance", "instances", "lambda", "container", "kubernetes", "eks",
            "ecs", "fargate", "compute", "autoscaling", "auto-scaling",
        }
    ),
    "data": frozenset(
        {
            "s3", "bucket", "buckets", "rds", "dynamodb", "database", "databases",
            "storage", "efs", "redshift", "elasticache",
        }
    ),
    "security": frozenset(
        {
            "kms", "encrypted", "encryption", "iam", "security",
            "firewall", "waf", "certificate", "certificates", "secret", "secrets", "guardduty",
            "role", "roles", "permission", "permissions",
        }
    ),
    "integration": frozenset(
        {
            "sns", "sqs", "eventbridge", "api-gateway", "cloudfront", "step-function",
            "pipeline", "codepipeline", "codebuild", "queue", "queues", "event", "events",
        }
    ),
}

_TOKEN_SPLIT = str.maketrans({ch: " " for ch in ".,;:!?()[]{}\"'„“”/\\"})


def classify_fact_topic(statement: str) -> str:
    tokens = {token for token in str(statement or "").lower().translate(_TOKEN_SPLIT).split() if token}
    if not tokens:
        return ""
    hits = [key for key, words in KNOWLEDGE_TOPIC_KEYWORDS.items() if tokens & words]
    return hits[0] if len(hits) == 1 else ""


__all__ = [
    "CATALOGUED_TYPES",
    "KNOWLEDGE_TOPIC_KEYWORDS",
    "OTHER_THEME",
    "THEME_CATALOG",
    "THEME_TOPIC_KEYS",
    "classify_fact_topic",
    "theme_buckets",
]
