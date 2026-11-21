"""Publishing a flow exposes a workflow capability descriptor with its executable process summary, unpublishing hides it, and the tool name is stable and bounded."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, FlowDefinition, FlowDefinitionVersion
from app.services.flow_capabilities import (
    list_flow_capabilities,
    list_flow_tool_definitions,
    unpublish_flow_definition_version,
    workflow_tool_name_for_key,
)
from app.services.flow_definitions import publish_flow_definition_version
from tests.flow_capabilities_support import _admin_user, _make_draft_flow, _tool_context


@pytest.mark.asyncio
async def test_publish_exposes_flow_capability_descriptor(db):
    admin_user = await _admin_user(db)
    _, version = _make_draft_flow(db, created_by=admin_user.id)
    await publish_flow_definition_version(
        db,
        version_id=version.id,
        current_user=admin_user,
        publish_metadata={
            "purpose": "Use when a user asks who a person is and source evidence is required.",
            "limitations": ["Does not invent missing identity facts."],
        },
    )

    capabilities = await list_flow_capabilities(db)
    tool_definitions = await list_flow_tool_definitions(db, _tool_context(db))

    assert capabilities[0]["tool_name"] == "run_flow_person_research"
    assert capabilities[0]["available"] is True
    assert capabilities[0]["input_schema"]["required"] == ["request"]
    assert tool_definitions[0]["function"]["name"] == "run_flow_person_research"
    assert "source evidence" in tool_definitions[0]["function"]["description"]
    audit_actions = {row.action for row in (await db.execute(select(AuditLog))).scalars().all()}
    assert "workflow.capability_exposed" in audit_actions


@pytest.mark.asyncio
async def test_published_flow_tool_descriptor_includes_executable_process_summary(db):
    admin_user = await _admin_user(db)
    flow = FlowDefinition(
        id="flow-process-cap",
        key="person-source-evidence-research",
        name="Person Source-Evidence Research",
        description="Find who a person is using source evidence.",
        status="draft",
        is_active=True,
        created_by=admin_user.id,
    )
    version = FlowDefinitionVersion(
        id="version-process-cap",
        flow_id=flow.id,
        version=1,
        status="draft",
        definition_json={
            "schema_version": "2.0",
            "nodes": [
                {
                    "id": "input",
                    "type": "trigger",
                    "label": "Person question",
                    "output_schema": {"request": "string", "subject_hint": "string"},
                },
                {
                    "id": "identity",
                    "type": "tool_step",
                    "label": "Resolve identity",
                    "input_schema": {"request": "string", "subject_hint": "string"},
                    "output_schema": {"identity": "object", "has_identity": "boolean"},
                    "config": {"tool": "search_jira_users"},
                },
                {
                    "id": "route",
                    "type": "router",
                    "label": "Identity found?",
                    "input_schema": {"has_identity": "boolean"},
                    "output_schema": {"route": "string", "input": "object"},
                    "config": {
                        "routes": [
                            {"route": "found", "when": {"field": "has_identity", "operator": "equals", "value": True}},
                            {"route": "missing", "when": {"field": "has_identity", "operator": "equals", "value": False}},
                        ],
                        "default_route": "missing",
                    },
                },
                {
                    "id": "activity",
                    "type": "retrieval",
                    "label": "Collect cross-source activity",
                    "input_schema": {"input": "object"},
                    "output_schema": {"evidence": "array"},
                    "config": {"allowed_tools": ["knowledge_search", "search_jira_tickets"]},
                },
                {
                    "id": "out",
                    "type": "output",
                    "label": "Return evidence-backed profile",
                    "input_schema": {"evidence": "array"},
                },
                # Every branch the router can pick needs a connection; it never just runs the first one.
                {"id": "no_identity", "type": "output", "label": "Report that no identity was found", "input_schema": {"route": "string"}},
            ],
            "edges": [
                {"source_node_id": "input", "target_node_id": "identity"},
                {
                    "source_node_id": "identity",
                    "target_node_id": "route",
                    "source_field": "has_identity",
                    "target_field": "has_identity",
                },
                {"source_node_id": "route", "target_node_id": "activity", "condition": "route:found"},
                {"source_node_id": "activity", "target_node_id": "out"},
                {"source_node_id": "route", "target_node_id": "no_identity", "condition": "route:missing"},
            ],
            "evidence_contract": {"required_source_families": ["identity", "work_items", "knowledge"]},
        },
        created_by=admin_user.id,
    )
    db.add_all([flow, version])

    await publish_flow_definition_version(
        db,
        version_id=version.id,
        current_user=admin_user,
        publish_metadata={"purpose": "Use when the user asks who a person is and source evidence is required."},
    )

    capability = (await list_flow_capabilities(db))[0]
    tool_definition = (await list_flow_tool_definitions(db, _tool_context(db)))[0]
    description = tool_definition["function"]["description"]

    assert capability["process_summary"][1]["tools"] == ["search_jira_users"]
    assert capability["process_summary"][2]["branches"][0]["route"] == "found"
    assert "Process:" in description
    assert "Resolve identity" in description
    assert "`search_jira_users`" in description
    assert "branches found" in description


@pytest.mark.asyncio
async def test_unpublish_hides_capability_from_tool_catalog(db):
    admin_user = await _admin_user(db)
    _, version = _make_draft_flow(db, created_by=admin_user.id)
    await publish_flow_definition_version(db, version_id=version.id, current_user=admin_user)

    await unpublish_flow_definition_version(
        db,
        version_id=version.id,
        current_user=admin_user,
        reason="Retired during test",
    )

    names = {item["function"]["name"] for item in await list_flow_tool_definitions(db, _tool_context(db))}
    assert "run_flow_person_research" not in names
    hidden_names = {item["tool_name"] for item in await list_flow_capabilities(db, include_hidden=True)}
    assert "run_flow_person_research" not in hidden_names
    audit_actions = {row.action for row in (await db.execute(select(AuditLog))).scalars().all()}
    assert "workflow.capability_hidden" in audit_actions


def test_workflow_tool_name_is_stable_and_bounded():
    assert workflow_tool_name_for_key("Release Analysis") == "run_flow_release_analysis"
    assert len(workflow_tool_name_for_key("x" * 120)) <= 64
