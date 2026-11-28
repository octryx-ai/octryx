"""Service-inventory board: the complete "what runs on AWS" view."""

from __future__ import annotations

from typing import Any

from .aws_cell_text import _truncate_label, _xml_value
from .aws_structural_autolayout import wrap_grid
from .aws_topology_cells import _coverage_gap_note, _title_cell
from .aws_topology_shapes import _DEFAULT_ICON_FILL, _NODE_TYPE_ICON_FILLS

_CARD_W = 300
_CARD_BASE_H = 64
_NAME_LINE_H = 16
_MAX_NAMES_PER_CARD = 6
_GAP_X = 18
_GAP_Y = 18
_CANVAS_X = 40
_CANVAS_Y = 190
_BOARD_MAX_W = 4 * _CARD_W + 3 * _GAP_X

# Types that are structure rather than "running workload"; the architecture
# overview already shows them and they would drown the inventory.
_EXCLUDED_TYPES = {
    "aws_account",
    "cidr",
    "subnet",
    "route_table",
    "security_group",
    "target_group",
    "vpc_endpoint",
}

_TYPE_LABELS = {
    "vpc": "VPCs",
    "internet_gateway": "Internet gateways",
    "nat_gateway": "NAT gateways",
    "load_balancer": "Load balancers",
    "eks_cluster": "EKS clusters",
    "eks_nodegroup": "EKS nodegroups",
    "autoscaling_group": "Auto Scaling groups",
    "ec2_instance": "EC2 instances",
    "lambda_function": "Lambda functions",
    "ecs_cluster": "ECS clusters",
    "ecs_service": "ECS services",
    "rds_instance": "RDS instances",
    "rds_cluster": "RDS clusters",
    "rds_proxy": "RDS proxies",
    "dynamodb_table": "DynamoDB tables",
    "elasticache_cluster": "ElastiCache clusters",
    "s3_bucket": "S3 buckets",
    "efs_file_system": "EFS file systems",
    "ecr_repository": "ECR repositories",
    "sqs_queue": "SQS queues",
    "sns_topic": "SNS topics",
    "step_function": "Step Functions",
    "eventbridge_bus": "EventBridge buses",
    "secrets_manager_secret": "Secrets Manager secrets",
    "kms_key": "KMS keys",
    "codepipeline": "CodePipeline pipelines",
    "cloudfront_distribution": "CloudFront distributions",
    "route53_zone": "Route 53 zones",
    "api_gateway": "API Gateways",
    "waf_web_acl": "WAF web ACLs",
    "vpc_peering": "VPC peering connections",
    "transit_gateway": "Transit gateways",
    "kinesis_stream": "Kinesis streams",
    "bedrock_model": "Bedrock models (catalog)",
}


def build_inventory_cards(
    topology_result: dict[str, Any],
    selected_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    summary = topology_result.get("service_summary") if isinstance(topology_result, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    counts = summary.get("node_counts_by_type")
    counts = dict(counts) if isinstance(counts, dict) else {}
    names_by_type: dict[str, list[str]] = {}
    for node in selected_nodes:
        node_type = str(node.get("type") or "").strip()
        label = str(node.get("label") or "").strip()
        if not node_type or not label:
            continue
        bucket = names_by_type.setdefault(node_type, [])
        if len(bucket) < _MAX_NAMES_PER_CARD and label not in bucket:
            bucket.append(label)
    if not counts:
        # fall back to the brief when the full summary is unavailable
        for node in selected_nodes:
            node_type = str(node.get("type") or "").strip()
            if node_type:
                counts[node_type] = counts.get(node_type, 0) + 1

    cards: list[dict[str, Any]] = []
    for node_type, count in counts.items():
        if node_type in _EXCLUDED_TYPES or not count:
            continue
        try:
            total = int(count)
        except (TypeError, ValueError):
            continue
        names = names_by_type.get(node_type, [])
        cards.append(
            {
                "type": node_type,
                "label": _TYPE_LABELS.get(node_type, node_type.replace("_", " ").title()),
                "count": total,
                "names": names,
                "more": max(0, total - len(names)),
            }
        )
    cards.sort(key=lambda card: (-card["count"], card["label"]))
    return cards


def render_inventory_board_xml(
    *,
    title: str,
    topology_result: dict[str, Any],
    selected_nodes: list[dict[str, Any]],
) -> str:
    cards = build_inventory_cards(topology_result, selected_nodes)
    if not cards:
        return ""

    total = sum(card["count"] for card in cards)
    cells: list[str] = [_title_cell(title, topology_result)]
    legend = (
        f"Complete service inventory from aws_topology_snapshot: {total} resources across "
        f"{len(cards)} resource types. Counts are account totals; names are examples. "
        "The architecture overview shows structure and traffic; this board shows everything that exists."
    )
    coverage_gap = _coverage_gap_note(topology_result)
    if coverage_gap:
        legend = f"{legend} {coverage_gap}"
    cells.append(
        f'<mxCell id="topology_legend" value="{_xml_value(legend)}" '
        'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8fafc;strokeColor=#cbd5e1;'
        'fontSize=12;fontColor=#334155;align=left;verticalAlign=top;spacing=10;" vertex="1" parent="1">'
        '<mxGeometry x="60" y="92" width="1480" height="64" as="geometry"/></mxCell>'
    )

    sizes = []
    for card in cards:
        lines = len(card["names"]) + (1 if card["more"] else 0)
        sizes.append((_CARD_W, _CARD_BASE_H + lines * _NAME_LINE_H))
    rects, _, _ = wrap_grid(sizes, max_width=_BOARD_MAX_W, gap_x=_GAP_X, gap_y=_GAP_Y)

    for index, (card, (x, y, w, h)) in enumerate(zip(cards, rects)):
        fill = _NODE_TYPE_ICON_FILLS.get(card["type"], _DEFAULT_ICON_FILL)
        name_lines = list(card["names"])
        if card["more"]:
            name_lines.append(f"+{card['more']} more")
        body = "&#xa;".join(
            _xml_value(_truncate_label(line, 40)) for line in name_lines
        )
        # html=1 labels render &lt;b&gt; as bold; raw tags would break the XML attribute
        value = f"&lt;b&gt;{card['count']} x {_xml_value(card['label'])}&lt;/b&gt;"
        if body:
            value = f"{value}&#xa;{body}"
        cells.append(
            f'<mxCell id="inv_{index}" value="{value}" '
            f'style="rounded=1;arcSize=6;whiteSpace=wrap;html=1;fontSize=11;align=left;'
            f"verticalAlign=top;spacing=8;fillColor=#ffffff;strokeColor={fill};"
            f'strokeWidth=2;fontColor=#1f2937;" vertex="1" parent="1">'
            f'<mxGeometry x="{_CANVAS_X + x}" y="{_CANVAS_Y + y}" width="{w}" height="{h}" as="geometry"/>'
            "</mxCell>"
        )
    return "".join(cells)
