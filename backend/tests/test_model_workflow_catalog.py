"""Tests for the model-side workflow catalog."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.core.prompts.prompt_builder import build_system_prompt_parts
from app.services.agent_mode import DEFAULT_AGENT_MODE_KEY
from app.services.workflow_routing.model_catalog import (
    MODEL_WORKFLOW_CATALOG_MAX_ENTRIES,
    MODEL_WORKFLOW_CATALOG_MAX_ONE_LINER_CHARS,
    build_model_workflow_catalog,
    render_model_workflow_catalog_prompt,
)


@pytest.mark.asyncio
async def test_catalog_lists_all_seed_definitions_with_when_to_use(db):
    catalog = await build_model_workflow_catalog(db)

    # The 6 shipped phased workflows the suite's baseline has active (team-delivery is optional, switched on there)
    # + B (feature-delivery-tdd), which the suite publishes as an admin would: an admin's own workflow is offered
    # like any other. The PR bots are not chat.
    assert len(catalog) == 6 + 1
    keys = [entry["workflow_key"] for entry in catalog]
    assert {"bug-fix-reproduction", "jira-intake-triage", "incident-analysis", "epic-delivery"} <= set(keys)
    assert "feature-delivery-tdd" in keys
    assert "team-delivery" in keys
    assert "pr-review-bot" not in keys  # only a pull request webhook or the bot's sync starts it
    assert "pr-review-explain" not in keys  # only an ``@octryx explain`` comment starts it
    assert "pr-fix" not in keys  # only an ``@octryx fix`` / ``write tests`` comment starts it
    assert keys == sorted(keys), "catalog order must be deterministic (sorted by key)"
    for entry in catalog:
        assert entry["title"]
        assert entry["when_to_use"], entry["workflow_key"]
        assert len(entry["when_to_use"]) <= MODEL_WORKFLOW_CATALOG_MAX_ONE_LINER_CHARS
        assert entry["capability"] in {"diagnosis", "change"}
    assert len(catalog) <= MODEL_WORKFLOW_CATALOG_MAX_ENTRIES


@pytest.mark.asyncio
async def test_catalog_resolution_is_deterministic(db):
    first = await build_model_workflow_catalog(db)
    second = await build_model_workflow_catalog(db)
    assert first == second


def test_render_catalog_prompt_is_compact_and_bounded():
    catalog = [
        {
            "workflow_key": "aws-topology-diagram-routing",
            "title": "AWS topology diagram routing",
            "when_to_use": "Use for AWS architecture diagrams.",
            "capability": "diagnosis",
        }
    ]
    rendered = render_model_workflow_catalog_prompt(catalog)

    assert rendered.startswith("## Workflow catalog")
    assert "select_workflow" in rendered
    assert "- aws-topology-diagram-routing [diagnosis]: Use for AWS architecture diagrams." in rendered
    assert render_model_workflow_catalog_prompt([]) == ""


@pytest.mark.asyncio
async def test_workflows_endpoint_includes_when_to_use(client, auth_headers):
    resp = await client.get("/chat/api/workflows", headers=auth_headers)

    assert resp.status_code == 200
    workflows = resp.json()["workflows"]
    assert workflows
    for item in workflows:
        assert item["when_to_use"], item["key"]


@pytest.mark.parametrize("prompt_variant", ["full", "minimal", "summary", "admin", "bounded_evidence"])
def test_system_prompt_contains_catalog_in_every_variant(prompt_variant):
    agent_mode = SimpleNamespace(
        key=DEFAULT_AGENT_MODE_KEY,
        name="Diagnosis",
        capability_type="diagnosis",
        prompt_instructions="",
    )
    catalog_block = render_model_workflow_catalog_prompt(
        [
            {
                "workflow_key": "aws-topology-diagram-routing",
                "title": "AWS topology diagram routing",
                "when_to_use": "Use for AWS architecture diagrams.",
                "capability": "diagnosis",
            }
        ]
    )

    parts = build_system_prompt_parts(
        agent_type=DEFAULT_AGENT_MODE_KEY,
        agent_mode=agent_mode,
        personality="",
        memory="",
        skills="",
        prompt_variant=prompt_variant,
        workflow_catalog=catalog_block,
    )

    assert "## Workflow catalog" in parts.stable
    assert "aws-topology-diagram-routing" in parts.stable
