"""Styles, geometry and edge-selection rules for the structural AWS overview layout."""

from __future__ import annotations

# Traffic-flow layers for the dot layout: ingress plumbing on top, compute in
# the middle, data stores at the bottom. Unlisted types default to the middle.
_FLOW_LAYERS = {
    # edge / ingress
    "cloudfront_distribution": 0,
    "route53_zone": 0,
    "internet_gateway": 0,
    "nat_gateway": 0,
    "waf_web_acl": 0,
    "api_gateway": 1,
    "load_balancer": 1,
    "route_table": 1,
    # compute
    "target_group": 2,
    "eks_nodegroup": 2,
    "autoscaling_group": 2,
    "lambda_function": 2,
    "ecs_service": 2,
    "ec2_instance": 2,
    "step_function": 2,
    "eks_cluster": 3,
    "ecs_cluster": 3,
    # integration (between compute and data)
    "sqs_queue": 3,
    "sns_topic": 3,
    "eventbridge_bus": 3,
    "kinesis_stream": 3,
    "msk_cluster": 3,
    "mq_broker": 3,
    # data / persistence
    "rds_proxy": 4,
    "rds_instance": 4,
    "rds_cluster": 4,
    "dynamodb_table": 4,
    "elasticache_cluster": 4,
    "redshift_cluster": 4,
    "efs_file_system": 4,
}
_DEFAULT_FLOW_LAYER = 2

_GROUP_BASE = (
    "outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;"
    "container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
    "verticalAlign=top;align=left;spacingLeft=30;"
)
_AWS_CLOUD_STYLE = (
    _GROUP_BASE + "fontStyle=1;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud_alt;"
    "strokeColor=#232F3E;fillColor=none;fontColor=#232F3E;dashed=0;"
)
_VPC_STYLE = (
    _GROUP_BASE + "fontStyle=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;"
    "strokeColor=#8C4FFF;fillColor=none;fontColor=#8C4FFF;dashed=0;"
)
# Official aws4 subnet group colors: public green, private blue, db teal.
_SUBNET_TIER_STYLES = {
    "public": ("#E9F3E6", "#248814", "#248814"),
    "private": ("#E6F2F8", "#147EBA", "#147EBA"),
    "db": ("#E7F0F1", "#2E73B8", "#1B660F"),
    "other": ("#F2F3F3", "#5A6B86", "#5A6B86"),
}
_TIER_LABELS = {
    "public": "Public subnets",
    "private": "Private subnets",
    "db": "Database subnets",
    "other": "Subnets (tier unknown)",
}
_TIER_ORDER = ("public", "private", "db", "other")
_SUBNET_GROUP_STYLE = (
    _GROUP_BASE + "fontSize=11;fontStyle=0;shape=mxgraph.aws4.group;"
    "grIcon=mxgraph.aws4.group_subnet;grStroke=0;dashed=0;"
    "fillColor={fill};strokeColor={stroke};fontColor={font};"
)
_REGIONAL_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;fontSize=12;fontStyle=0;container=1;"
    "collapsible=0;recursiveResize=0;verticalAlign=top;align=left;spacing=8;"
    "fillColor=none;strokeColor=#5A6B86;fontColor=#232F3E;dashed=1;"
)
# Official aws4 region group: dashed teal frame with the region icon.
_REGION_STYLE = (
    _GROUP_BASE + "fontStyle=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_region;"
    "strokeColor=#00A4A6;fillColor=none;fontColor=#00A4A6;dashed=1;"
)
_INTER_VPC_EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=none;fontSize=9;"
    "strokeWidth=2;strokeColor=#8C4FFF;fontColor=#6b21a8;"
)

_ICON_SLOT_W = 136
_ICON_SLOT_H = 124
_ICON_SIZE = 64
_ICON_LABEL_WIDTH = 124
_LABEL_MAX = 26
_SUBTITLE_MAX = 42
_SUBNET_PAD = 14
_SUBNET_TITLE_H = 30
_VPC_PAD = 24
_VPC_TITLE_H = 36
_CLOUD_PAD = 28
_CLOUD_TITLE_H = 40
_REGION_PAD = 24
_REGION_TITLE_H = 36
_CANVAS_X = 40
_CANVAS_Y = 190

# Membership these container assignments replace on the canvas.
_CONTAINMENT_EDGE_TYPES = {"belongs_to", "uses_subnet", "runs_in", "attached_to", "uses_route_table"}
# Overview keeps structure only; security wiring has its own detail diagram.
_EXCLUDED_NODE_TYPES = {"security_group", "cidr", "aws_account"}
_KEPT_EDGE_TYPES = {
    "routes_to",
    "protects",
    "backs",
    "targets",
    "serves",
    "connects_to",
    # deep wiring: DNS chain + event wiring
    "resolves_to",
    "triggers",
    "delivers_to",
}
# belongs_to between resources (e.g. nodegroup -> cluster) stays informative.
_KEPT_RESOURCE_BELONGS_TO_TYPES = {("eks_nodegroup", "eks_cluster")}
# Node types without their own VPC evidence that still belong next to the VPC
# resources they are wired to (keeps their edges short instead of spanning the
# whole canvas from the regional group). Edge/ingress services (WAF, CloudFront,
# Route 53) have no subnet but front a specific VPC resource; drawing them in
# that VPC's ingress band matches the AWS reference diagrams and avoids long
# protects/serves edges from the regional group.
_PULLED_INTO_VPC_TYPES = {
    "target_group",
    "autoscaling_group",
    "waf_web_acl",
    "cloudfront_distribution",
    "route53_zone",
}

_INTER_VPC_EDGE_LABELS = {"vpc_peering": "peers", "transit_gateway": "attached"}
