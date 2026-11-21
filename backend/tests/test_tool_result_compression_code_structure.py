"""code_structure_snapshot compression must preserve the diagram_brief evidence."""

from __future__ import annotations

from app.services.tool_result_compression.budget import COMPACT_RESULT_TOKEN_BUDGET_KEY
from app.services.tool_result_compression.registry import get_strategy_handler
from app.services.tool_result_compression.service import DEFAULT_COMPRESSORS
from app.services.tool_result_compression.strategy_code_structure import (
    _compress_code_structure_snapshot,
)


def _snapshot_result(node_count: int = 3, edge_count: int = 2) -> dict:
    return {
        "workspace": "/tmp/workspace",
        "generated_at": "2026-07-18T00:00:00+00:00",
        "service_summary": {"file_count": 28, "class_count": 1464, "package_count": 13},
        "scope": {"languages": ["java"], "paths": []},
        "diagram_brief": {
            "selected_nodes": [
                {"ref": f"class:C{index}", "type": "project", "label": f"C{index}", "attributes": {"fields": []}}
                for index in range(node_count)
            ],
            "selected_edges": [
                {"source_ref": "class:C0", "target_ref": f"class:C{index + 1}", "relation": "uses"}
                for index in range(edge_count)
            ],
            "truncated": False,
        },
        "warnings": ["file skipped (too large): conf/project.ini"],
    }


def test_default_compressor_registered_for_code_structure_snapshot() -> None:
    definition = DEFAULT_COMPRESSORS["code_structure_snapshot"]
    assert definition["strategy"] == "code_structure_snapshot_summary"
    assert get_strategy_handler("code_structure_snapshot_summary") is not None


def test_strategy_preserves_diagram_brief_and_sets_budget() -> None:
    compact = _compress_code_structure_snapshot(_snapshot_result(), DEFAULT_COMPRESSORS["code_structure_snapshot"]["config"])
    assert compact is not None
    brief = compact["diagram_brief"]
    assert len(brief["selected_nodes"]) == 3
    assert len(brief["selected_edges"]) == 2
    assert brief["selected_nodes"][0]["attributes"] == {"fields": []}
    assert compact[COMPACT_RESULT_TOKEN_BUDGET_KEY] == 48000
    assert compact["service_summary"]["class_count"] == 1464


def test_strategy_bounds_are_explicit() -> None:
    compact = _compress_code_structure_snapshot(
        _snapshot_result(node_count=10, edge_count=6),
        {"max_diagram_nodes": 4, "max_diagram_edges": 4},
    )
    assert compact is not None
    brief = compact["diagram_brief"]
    assert len(brief["selected_nodes"]) == 4
    assert brief["omitted_node_count"] == 6
    assert len(brief["selected_edges"]) == 4
    assert brief["omitted_edge_count"] == 2
    assert brief["truncated"] is True


def test_strategy_returns_none_without_diagram_brief() -> None:
    assert _compress_code_structure_snapshot({"error": "no matching source files"}, {}) is None


def test_terraform_provider_attributes_survive_compression() -> None:
    result = _snapshot_result(node_count=1)
    result["service_summary"]["counts_by_language"] = {"terraform": 3}
    result["diagram_brief"]["selected_nodes"][0]["attributes"] = {
        "block": "resource",
        "resource_type": "aws_lb",
        "provider": "aws",
        "package": "modules.network",
        "file": "modules/network/alb.tf",
        "fields": ["name", "subnets"],
    }
    compact = _compress_code_structure_snapshot(result, DEFAULT_COMPRESSORS["code_structure_snapshot"]["config"])
    assert compact is not None
    attributes = compact["diagram_brief"]["selected_nodes"][0]["attributes"]
    # the dedicated Terraform view reads these keys from the COMPACT history
    assert attributes["resource_type"] == "aws_lb"
    assert attributes["provider"] == "aws"
    assert attributes["block"] == "resource"
    assert attributes["package"] == "modules.network"
    assert compact["service_summary"]["counts_by_language"] == {"terraform": 3}


def test_full_repo_terraform_brief_survives_the_token_budget() -> None:
    # A full-repository terraform snapshot under the module quota carries
    # ~211 nodes with fields and long workspace file paths. The compact
    # result must stay under its own token budget so the generic budget
    # enforcement never pushes it into the diagram shrink ladder (live
    # finding: a 24k budget cut the history brief to 40 nodes and collapsed
    # the module-detail set to a single module).
    from app.services.tool_result_compression.budget import enforce_compact_result_budget
    from app.services.tool_result_compression.support import _estimate_tokens

    result = _snapshot_result(node_count=0, edge_count=0)
    result["service_summary"]["counts_by_language"] = {"terraform": 87}
    prefix = "var.repos.bitbucket.SHOP.aws-shop-infrastructure.terraform"
    resource_types = [
        "aws_subnet",
        "aws_sqs_queue",
        "aws_iam_role_policy_attachment",
        "aws_db_proxy",
        "aws_route_table",
    ]
    nodes = []
    for index in range(211):
        module = f"{prefix}.module{index % 11}"
        resource_type = resource_types[index % len(resource_types)]
        nodes.append(
            {
                "ref": f"class:{module}.{resource_type}.name_{index}",
                "type": "resource",
                "label": f"{resource_type}.name_{index}",
                "attributes": {
                    "block": "resource",
                    "resource_type": resource_type,
                    "provider": "aws",
                    "package": module,
                    "file": f"{prefix.replace('.', '/')}/module{index % 11}/main_{index}.tf",
                    # real blocks average a handful of argument keys (many
                    # variables/outputs/data blocks carry 1-3)
                    "fields": [f"argument_key_{field}" for field in range(4)],
                    "fields_truncated": 0,
                    "methods": [],
                    "methods_truncated": 0,
                },
            }
        )
    for module_index in range(11):
        nodes.append(
            {
                "ref": f"package:{prefix}.module{module_index}",
                "type": "package",
                "label": f"{prefix}.module{module_index}",
                "attributes": {"class_count": 20, "selected_count": 20},
            }
        )
    result["diagram_brief"]["selected_nodes"] = nodes
    result["diagram_brief"]["selected_edges"] = [
        {"source_ref": nodes[index % 211]["ref"], "target_ref": nodes[(index + 1) % 211]["ref"], "type": "uses"}
        for index in range(300)
    ]
    compact = _compress_code_structure_snapshot(result, DEFAULT_COMPRESSORS["code_structure_snapshot"]["config"])
    assert compact is not None
    # the repeated workspace prefix is stripped consistently and stated
    assert compact["package_prefix_stripped"] == prefix
    stripped_nodes = compact["diagram_brief"]["selected_nodes"]
    assert stripped_nodes[0]["ref"].startswith("class:module0.")
    assert stripped_nodes[0]["attributes"]["package"] == "module0"
    assert stripped_nodes[0]["attributes"]["file"].startswith("module0/")
    assert compact["diagram_brief"]["selected_edges"][0]["source_ref"].startswith("class:module0.")
    budget = compact[COMPACT_RESULT_TOKEN_BUDGET_KEY]
    assert _estimate_tokens(compact) <= budget
    enforced = enforce_compact_result_budget(compact, token_budget=budget)
    # no shrink ladder: every module's nodes survive into the turn history
    assert len(enforced["diagram_brief"]["selected_nodes"]) == 222


def test_pipeline_steps_survive_with_explicit_truncation_counter() -> None:
    result = _snapshot_result(node_count=1)
    result["diagram_brief"]["selected_nodes"][0]["attributes"] = {
        "pipeline_steps": [f"Plugin{index:02d}" for index in range(30)],
        "pipeline_steps_truncated": 5,
    }
    compact = _compress_code_structure_snapshot(result, DEFAULT_COMPRESSORS["code_structure_snapshot"]["config"])
    assert compact is not None
    attributes = compact["diagram_brief"]["selected_nodes"][0]["attributes"]
    # renderer shows up to 24 steps: keep them ORDERED, no "+N more" string
    assert attributes["pipeline_steps"] == [f"Plugin{index:02d}" for index in range(24)]
    # 6 dropped here + 5 already dropped by the parser -> one explicit counter
    assert attributes["pipeline_steps_truncated"] == 11
