"""Shared AWS snapshot, template, diagram and knowledge fact fixtures for the test_office_identity_aws_deck_plan_* modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.office_identity.aws_deck_plan import build_aws_deck_plan

#: Plan-level cases only carry the path through; the end-to-end case writes a
#: real PNG at test time and passes it to ``_diagram_images``.
DIAGRAM_PNG = Path("diagrams") / "aws-overview.png"


def _aws_snapshot() -> dict[str, Any]:
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "generated_at": "2026-07-20T09:15:00+00:00",
        "service_summary": {
            "evidence_kind": "aws_topology_inventory",
            "account_id": "123456789012",
            "region": "eu-central-1",
            "resource_node_count": 41,
            "edge_count": 57,
            "services_requested": ["ec2", "eks", "rds", "dynamodb", "s3", "elbv2", "iam", "lambda"],
            "services_succeeded": ["dynamodb", "ec2", "eks", "elbv2", "iam", "rds", "s3"],
            "services_failed": ["s3"],
            "services_skipped": ["lambda"],
            "services_partial": ["s3"],
            "services_with_nodes": ["dynamodb", "ec2", "eks", "elbv2", "iam", "rds"],
            "inventory_services_with_resources": ["dynamodb", "ec2", "eks", "elbv2", "rds"],
            "identity_evidence_services": ["iam"],
            "catalog_visibility_services": [],
            "services_checked_no_resources": ["dynamodb"],
            "node_counts_by_service": {"ec2": 26, "eks": 3, "elbv2": 2, "iam": 6, "rds": 4},
            "node_counts_by_type": {
                "cidr": 3,
                "eks_cluster": 1,
                "eks_nodegroup": 2,
                "iam_role": 6,
                "internet_gateway": 1,
                "load_balancer": 2,
                "nat_gateway": 2,
                "rds_instance": 3,
                "rds_cluster": 1,
                "security_group": 7,
                "subnet": 6,
                "vpc": 1,
                "quantum_flux_capacitor": 6,
            },
            "edge_counts_by_service": {"ec2": 38, "eks": 6, "elbv2": 7, "rds": 6},
            "warning_count": 2,
            "warning_counts_by_service": {"s3": 2},
            "warnings_by_service": {
                "s3": [
                    {
                        "operation": "GetBucketPolicy",
                        "severity": "warning",
                        "reason": "access_denied",
                        "message": "not authorized",
                    }
                ]
            },
        },
        "scope": {
            "project_ids": [],
            "regions": ["eu-central-1", "eu-west-1"],
            "services_requested": ["ec2", "eks", "rds", "dynamodb", "s3", "elbv2", "iam", "lambda"],
            "services_succeeded": ["dynamodb", "ec2", "eks", "elbv2", "iam", "rds", "s3"],
            "services_failed": ["s3"],
            "services_skipped": ["lambda"],
            "max_items": 200,
            "max_nodes": 400,
            "diagram_brief_requested": True,
        },
        "warnings": [
            {"service": "s3", "operation": "GetBucketPolicy", "reason": "access_denied"},
            {"service": "s3", "operation": "GetBucketTagging", "reason": "access_denied"},
        ],
    }


def _diagram_images(path: Path = DIAGRAM_PNG) -> list[dict[str, str]]:
    return [
        {
            "path": str(path),
            "title": "AWS topology — overview",
            "diagram_id": "aws-overview-dcd76f69",
        }
    ]


def _knowledge_facts() -> list[dict[str, str]]:
    return [
        {
            "statement": "The platform runs in production on EKS in eu-central-1",
            "source": "knowledge_graph:node/platform-runtime",
        },
        {
            "statement": "The data lives in RDS PostgreSQL with Multi-AZ",
            "source": "knowledge_graph:node/data-tier",
        },
    ]


def _plan(template_snapshot: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    return build_aws_deck_plan(_aws_snapshot(), template_snapshot, **kwargs)


def _minimal_template() -> dict[str, Any]:
    return {
        "slide_size": {"width_emu": 9144000, "height_emu": 5143500},
        "layouts": [
            # Mirrors the corporate title slide: title, subtitle and a
            # strapline body slot.
            {
                "key": "title-slide",
                "content_shape": "title_slide",
                "capacity": {
                    "content_units": 1,
                    "picture_slots": 0,
                    "title_slots": 1,
                    "subtitle_slots": 1,
                },
            },
            {
                "key": "title-and-subtitle",
                "content_shape": "title_and_subtitle",
                "capacity": {
                    "content_units": 0,
                    "picture_slots": 0,
                    "title_slots": 1,
                    "subtitle_slots": 1,
                },
            },
            {
                "key": "title-and-content",
                "content_shape": "bullets",
                "capacity": {
                    "content_units": 1,
                    "picture_slots": 0,
                    "title_slots": 1,
                    "subtitle_slots": 0,
                },
            },
            {
                "key": "diagram-full-generated",
                "content_shape": "diagram_full",
                "capacity": {
                    "content_units": 0,
                    "picture_slots": 1,
                    "title_slots": 1,
                    "subtitle_slots": 0,
                },
            },
        ],
    }


def _note_lines(entry: dict[str, Any]) -> list[str]:
    return str(entry.get("notes") or "").split("\n")


def _corporate_template() -> dict[str, Any]:
    template = _minimal_template()
    template["layouts"].extend(
        [
            {
                "key": "table-of-content",
                "content_shape": "agenda",
                "order": 10,
                "capacity": {
                    "content_units": 1,
                    "picture_slots": 0,
                    "title_slots": 1,
                    "subtitle_slots": 1,
                },
            },
            {
                "key": "section-header",
                "content_shape": "section",
                "order": 11,
                "capacity": {
                    "content_units": 0,
                    "picture_slots": 0,
                    "title_slots": 1,
                    "subtitle_slots": 1,
                },
            },
            {
                "key": "statement-title",
                "content_shape": "statement",
                "order": 12,
                "capacity": {
                    "content_units": 0,
                    "picture_slots": 0,
                    "title_slots": 1,
                    "subtitle_slots": 1,
                },
            },
            {
                "key": "icons-3-topics",
                "content_shape": "icons_3",
                "order": 13,
                "capacity": {
                    "content_units": 3,
                    "picture_slots": 0,
                    "title_slots": 1,
                    "subtitle_slots": 0,
                },
            },
        ]
    )
    return template
