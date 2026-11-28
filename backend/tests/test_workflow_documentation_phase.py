"""Workflow B's documentation phase: the output, the data-flow law and the rendered page, unit by unit."""

from __future__ import annotations

import copy

import pytest

from app.services.workflow_runs.documentation.page import render_storage
from app.services.workflow_runs.documentation.record import validate_feature_documentation
from app.services.workflow_runs.graph_validation import validate_phased_definition
from tests.documentation_acceptance_support import DOCUMENTATION
from tests.phased_seed_definitions import seed_definitions

pytestmark = pytest.mark.asyncio


def _b() -> dict:
    return copy.deepcopy(next(seed for seed in seed_definitions() if seed["key"] == "feature-delivery-tdd")["definition"])


def _codes(definition: dict) -> list[str]:
    return [error["code"] for error in validate_phased_definition(definition)["errors"]]


async def test_the_output_needs_title_what_why_and_how_to_use():
    record, problems = validate_feature_documentation({"title": "X", "what": "Y"})
    assert problems == ["why: missing", "how_to_use: missing"]
    record, problems = validate_feature_documentation(DOCUMENTATION)
    assert problems == [] and record["title"] == DOCUMENTATION["title"]


def _without(definition: dict, node_id: str, *, rewire: tuple[str, str]) -> dict:
    for edge in definition["edges"]:
        if edge["id"] == rewire[0]:
            edge["target_node_id"] = rewire[1]
    definition["edges"] = [edge for edge in definition["edges"]
                           if node_id not in (edge["source_node_id"], edge["target_node_id"])]
    definition["nodes"] = [node for node in definition["nodes"] if node["id"] != node_id]
    return definition


async def test_publish_validation_ensures_the_producer_chain():
    assert validate_phased_definition(_b())["valid"]
    assert "consumer_without_producer" in _codes(
        _without(_b(), "confirm_publication", rewire=("e-reserve", "publish_docs")))
    assert "consumer_without_producer" in _codes(
        _without(_b(), "publish_docs", rewire=("e-publication-confirmed", "docs_in_knowledge")))


async def test_the_page_escapes_the_prose_and_takes_tests_and_links_only_from_run_facts():
    body = render_storage({**DOCUMENTATION, "what": "<script>alert(1)</script>", "notes": ""},
                          [{"id": "AC1", "text": "Half up", "tests": ["tests/test_totals.py::test_up"],
                            "manual_only": False}],
                          {"ticket": {"key": "PAY-1", "url": "https://jira.example.test/browse/PAY-1"},
                           "pull_request": {"id": "1", "url": "https://github.example.test/acme/pay/pull/1"}},
                          run_id="r1")
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "tests/test_totals.py::test_up" in body and 'href="https://jira.example.test/browse/PAY-1"' in body


async def test_the_submit_tool_exists_in_chat_and_over_mcp():
    from app.services.mcp_workflow_run_tools import PHASE_OUTPUT_MCP_HANDLERS
    from app.tools.registry import TOOL_REGISTRY

    assert "submit_feature_documentation" in TOOL_REGISTRY
    assert "submit_feature_documentation" in PHASE_OUTPUT_MCP_HANDLERS
