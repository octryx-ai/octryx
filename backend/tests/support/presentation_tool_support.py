"""Shared helpers for the test_presentation_tool_* modules."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pptx import Presentation

from app.services.office_identity.template_normalization import normalize_template
from app.tools.context import ToolContext
from app.tools.presentation import CreatePresentationTool


@pytest.fixture(scope="module")
def composer_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("presentation-template")
    source = root / "source.pptx"
    Presentation().save(str(source))
    output = root / "normalized.pptx"
    manifest = normalize_template(source, output)
    return output if manifest.get("status") == "normalized" else source


def _aws_snapshot() -> dict[str, Any]:
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "generated_at": "2026-07-20T09:15:00+00:00",
        "service_summary": {
            "evidence_kind": "aws_topology_inventory",
            "account_id": "123456789012",
            "resource_node_count": 41,
            "edge_count": 57,
            "services_succeeded": ["ec2", "rds"],
            "services_failed": ["s3"],
            "services_skipped": ["lambda"],
            "services_partial": [],
            "services_checked_no_resources": [],
            "node_counts_by_type": {"vpc": 1, "subnet": 6, "rds_instance": 3, "security_group": 7},
            "warning_count": 2,
        },
        "scope": {"regions": ["eu-central-1", "eu-west-1"], "max_nodes": 400},
        "warnings": [{"service": "s3", "operation": "GetBucketPolicy", "reason": "access_denied"}],
    }


def _history_item(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"artifact_id": "", "tool_name": tool_name, "tool_call_id": "", "params": {}, "result": result}


def _context(workspace: Path, history: list[dict[str, Any]]) -> ToolContext:
    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={},
        workspace_root=str(workspace),
    )
    context.turn_tool_history = history
    return context


def _run(tool: CreatePresentationTool, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return asyncio.run(tool.execute(params, context))
