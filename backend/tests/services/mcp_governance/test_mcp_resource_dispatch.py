"""Dispatch and discovery decisions for governed MCP resources and prompts: every denial happens before any
connection, discovery comes from the Workspace catalog, and unknown items look like disabled ones."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import CapabilityType
from app.services.mcp_governance.resource_identity import MCP_RESOURCE_POLICY_NAME
from app.services.mcp_governance.resource_states import DISCOVERY_STATE_NONE_VISIBLE, DISCOVERY_STATE_NOT_MIRRORED
from app.tools.registry import execute_tool_with_plugins
from tests.services.mcp_governance.mcp_resource_dispatch_support import _enabled_resource_workspace, _get
from tests.support.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.support.mcp_resource_support import (
    DOC_URI,
    GET_PROMPT_TOOL,
    LIST_PROMPTS_TOOL,
    LIST_RESOURCES_TOOL,
    OTHER_PROMPT,
    OTHER_URI,
    PROMPT,
    READ_RESOURCE_TOOL,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mirror_catalog,
    prompt_binding,
    read_params,
    resource_binding,
    resource_context,
    resource_id,
    unverifiable_context,
)


@pytest.mark.asyncio
async def test_enabled_resource_and_prompt_are_discoverable_and_callable(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch)
    context = resource_context(workspace, db)

    resources = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)
    prompts = await execute_tool_with_plugins(LIST_PROMPTS_TOOL, {"server_name": SERVER}, context)
    read = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)
    rendered = await execute_tool_with_plugins(GET_PROMPT_TOOL, _get(), context)

    assert [entry["resource_id"] for entry in resources["resources"]] == [resource_id(DOC_URI)]
    # Discovery publishes the opaque identity and never the resource's URI.
    assert "uri" not in resources["resources"][0]
    assert resources["resources"][0]["risk"] == "read"
    assert resources["resources"][0]["approval_required"] is False
    assert resources["resource_governance"] == {
        "state": "enforced",
        "source": "workspace_catalog",
        "catalog_entries": 1,
        "visible": 1,
    }
    assert [entry["name"] for entry in prompts["prompts"]] == [PROMPT]
    assert read["contents"][0]["text"] == "# React"
    assert read["resource_id"] == resource_id(DOC_URI)
    assert rendered["messages"][0]["content"] == "Summarize react"
    # Discovery never connects; only the two dispatches did.
    assert manager.resource_lists == [] and manager.prompt_lists == []
    # The URI the transport receives comes from the catalog, never from the model.
    assert manager.resource_reads == [(SERVER, DOC_URI)]
    assert manager.prompt_gets == [(SERVER, PROMPT, {"topic": "react"})]


@pytest.mark.asyncio
async def test_discovery_only_shows_what_dispatch_admits(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch)
    await mirror_catalog(db, workspace, resources=[DOC_URI, OTHER_URI], prompts=[PROMPT, OTHER_PROMPT])
    context = resource_context(workspace, db)

    resources = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)
    denied = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(OTHER_URI), context)

    assert [entry["resource_id"] for entry in resources["resources"]] == [resource_id(DOC_URI)]
    assert resources["resource_governance"]["catalog_entries"] == 2
    assert denied["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_unknown_disabled_and_out_of_scope_denials_are_indistinguishable(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI, OTHER_URI])
    await enable_binding(db, await resource_binding(db, workspace, OTHER_URI), scopes=["change"])
    context = resource_context(workspace, db, capability_type="diagnosis")

    disabled = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(DOC_URI), context)
    unknown = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params("docs://never-mirrored"), context)
    out_of_scope = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(OTHER_URI), context)

    assert disabled == unknown == out_of_scope
    assert disabled["reason"] == "mcp_resource_not_available"
    assert disabled["tool_execution"]["category"] == "denied_by_policy"
    assert disabled["tool_execution"]["policy"] == MCP_RESOURCE_POLICY_NAME
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_hidden_retired_and_drifted_entries_deny_before_transport(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch)
    await mirror_catalog(db, workspace, resources=[DOC_URI, OTHER_URI], prompts=[PROMPT])
    hidden = await enable_binding(db, await resource_binding(db, workspace, OTHER_URI))
    hidden.binding_status = "hidden"
    retired_binding = await resource_binding(db, workspace, DOC_URI)
    retired_type = (
        await db.execute(select(CapabilityType).where(CapabilityType.id == retired_binding.capability_type_id))
    ).scalar_one()
    retired_type.is_active = False
    drifted = await prompt_binding(db, workspace, PROMPT)
    drifted.binding_config = {**drifted.binding_config, "reviewState": "needs_review"}
    await db.flush()
    context = resource_context(workspace, db)

    results = [
        await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(OTHER_URI), context),
        await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(DOC_URI), context),
        await execute_tool_with_plugins(GET_PROMPT_TOOL, _get(), context),
    ]

    for result in results:
        assert result["blocked_by"] == MCP_RESOURCE_POLICY_NAME
        assert result["reason"].endswith("_not_available")
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_a_matching_execution_scope_admits_a_scoped_entry(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch, scopes=["change"])

    denied = await execute_tool_with_plugins(
        READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db, capability_type="diagnosis")
    )
    allowed = await execute_tool_with_plugins(
        READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db, capability_type="change")
    )

    assert denied["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert allowed["contents"][0]["text"] == "# React"
    assert manager.resource_reads == [(SERVER, DOC_URI)]


@pytest.mark.asyncio
async def test_another_workspace_cannot_use_a_mirrored_entry(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch)
    other = await create_mcp_workspace(db)

    result = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(other, db))

    assert result["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert result["reason"] == "mcp_resource_not_available"
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_an_unverifiable_context_denies_discovery_and_dispatch(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch)

    for context in (
        unverifiable_context(workspace, db),
        unverifiable_context(workspace, db, project_ids=[workspace.project.id, "other-project"]),
        unverifiable_context(workspace, None),
    ):
        listing = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)
        read = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)
        assert listing["blocked_by"] == MCP_RESOURCE_POLICY_NAME
        assert listing["reason"] == "mcp_resource_governance_unverifiable"
        assert "resources" not in listing
        assert read["reason"] == "mcp_resource_governance_unverifiable"
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_discovery_states_name_why_a_listing_is_empty(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    context = resource_context(workspace, db)

    never_mirrored = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    nothing_visible = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)

    assert never_mirrored["count"] == 0
    assert never_mirrored["resource_governance"]["state"] == DISCOVERY_STATE_NOT_MIRRORED
    assert nothing_visible["count"] == 0
    assert nothing_visible["resource_governance"]["state"] == DISCOVERY_STATE_NONE_VISIBLE
    assert nothing_visible["resource_governance"]["catalog_entries"] == 1
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_an_inactive_server_denies_before_resource_governance_runs(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch)
    context = resource_context(workspace, db, enabled_servers=[])

    listing = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)
    read = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)

    for result in (listing, read):
        assert result["blocked_by"] == "mcp_access_policy"
        assert result["reason"] == "mcp_server_not_active_for_project"
    assert manager.touched_remote is False
