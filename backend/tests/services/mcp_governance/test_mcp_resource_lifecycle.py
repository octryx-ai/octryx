"""Upstream lifecycle of mirrored MCP resources and prompts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.admin.panel.admin_mcp_resource_service import mirror_mcp_server_resources_for_workspace
from app.services.mcp_governance.resource_identity import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_MISSING,
    MCP_PROMPT_KIND,
    MCP_RESOURCE_KIND,
    MCP_RESOURCE_POLICY_NAME,
    MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW,
)
from app.services.mcp_governance.resource_index import load_mcp_resource_index
from app.services.mcp_governance.resource_policy import decide_mcp_resource
from app.services.mcp_governance.resource_states import STATE_ALLOWED, STATE_UPSTREAM_MISSING
from app.tools.registry import execute_tool_with_plugins
from tests.support.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.support.mcp_resource_support import (
    DOC_URI,
    LIST_RESOURCES_TOOL,
    OTHER_URI,
    PROMPT,
    READ_RESOURCE_TOOL,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mcp_prompt,
    mirror_catalog,
    prompt_binding,
    read_params,
    register_mcp_server,
    resource_binding,
    resource_context,
    resource_id,
)


async def _state(db, workspace, *, kind: str, identity: str) -> str:
    index = await load_mcp_resource_index(db, workspace_id=workspace.project.id)
    return decide_mcp_resource(index, kind=kind, server_name=SERVER, identity=identity).state


@pytest.mark.asyncio
async def test_a_disappeared_item_is_marked_missing_and_stops_executing(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI, OTHER_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk="write", scopes=["diagnosis"])
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT))

    result = await mirror_catalog(db, workspace, resources=[OTHER_URI])

    assert result["resources"]["missing_entries"] == [resource_id(DOC_URI)]
    assert result["prompts"]["missing_entries"] == [PROMPT]
    binding = await resource_binding(db, workspace, DOC_URI)
    assert binding.binding_config["lifecycleState"] == LIFECYCLE_MISSING
    assert binding.binding_config["missingDetectedAt"]
    assert binding.is_enabled is False
    assert binding.policy_config["risk"] == "write"
    assert binding.intent_scopes == ["diagnosis"]

    denied = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))
    listing = await execute_tool_with_plugins(
        LIST_RESOURCES_TOOL, {"server_name": SERVER}, resource_context(workspace, db)
    )
    assert denied["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert denied["reason"] == "mcp_resource_not_available"
    assert listing["resources"] == []
    assert await _state(db, workspace, kind=MCP_RESOURCE_KIND, identity=resource_id(DOC_URI)) == STATE_UPSTREAM_MISSING
    assert await _state(db, workspace, kind=MCP_PROMPT_KIND, identity=PROMPT) == STATE_UPSTREAM_MISSING
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_re_enabling_a_missing_item_does_not_make_it_executable(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    await mirror_catalog(db, workspace, resources=[])

    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))

    result = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))
    assert result["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert await _state(db, workspace, kind=MCP_RESOURCE_KIND, identity=resource_id(DOC_URI)) == STATE_UPSTREAM_MISSING


@pytest.mark.asyncio
async def test_a_reappearing_item_returns_disabled_and_parked_for_review(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT))
    await mirror_catalog(db, workspace, resources=[], prompts=[])

    result = await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])

    assert result["resources"]["reappeared_entries"] == [resource_id(DOC_URI)]
    assert result["prompts"]["reappeared_entries"] == [PROMPT]
    for binding in (
        await resource_binding(db, workspace, DOC_URI),
        await prompt_binding(db, workspace, PROMPT),
    ):
        assert binding.binding_config["lifecycleState"] == LIFECYCLE_ACTIVE
        assert binding.binding_config["reappearedAt"]
        assert binding.binding_config["reviewState"] == MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW
        assert binding.is_enabled is False
        assert binding.is_default is False

    denied = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))
    assert denied["blocked_by"] == MCP_RESOURCE_POLICY_NAME


@pytest.mark.asyncio
async def test_retiring_an_item_is_idempotent_and_keeps_the_first_detection(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    first = await mirror_catalog(db, workspace, resources=[])
    detected_at = (await resource_binding(db, workspace, DOC_URI)).binding_config["missingDetectedAt"]

    second = await mirror_catalog(db, workspace, resources=[])

    assert first["resources"]["missing_entries"] == second["resources"]["missing_entries"] == [resource_id(DOC_URI)]
    assert (await resource_binding(db, workspace, DOC_URI)).binding_config["missingDetectedAt"] == detected_at


@pytest.mark.asyncio
async def test_a_mirror_run_never_retires_another_workspace_or_another_server(db, monkeypatch) -> None:
    other_server = "demo-two"
    workspace = await create_mcp_workspace(db)
    neighbour = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await mirror_catalog(db, workspace, resources=[OTHER_URI], server_name=other_server)
    await mirror_catalog(db, neighbour, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, neighbour, DOC_URI))

    await mirror_catalog(db, workspace, resources=[])

    assert (await resource_binding(db, workspace, DOC_URI)).binding_config["lifecycleState"] == LIFECYCLE_MISSING
    other = await resource_binding(db, workspace, OTHER_URI, server_name=other_server)
    assert other.binding_config.get("lifecycleState", LIFECYCLE_ACTIVE) == LIFECYCLE_ACTIVE
    assert (await resource_binding(db, neighbour, DOC_URI)).is_enabled is True
    assert await _state(db, neighbour, kind=MCP_RESOURCE_KIND, identity=resource_id(DOC_URI)) == "allowed_enabled"


class _MethodNotFoundError(Exception):
    error = SimpleNamespace(code=-32601)


async def _lifecycle_state(db, workspace, uri: str = DOC_URI) -> str:
    binding = await resource_binding(db, workspace, uri)
    return str((binding.binding_config or {}).get("lifecycleState") or LIFECYCLE_ACTIVE)


async def _mirror_through_admin(db, workspace, manager):
    await register_mcp_server(db, workspace)
    return await mirror_mcp_server_resources_for_workspace(
        db,
        server_name=SERVER,
        workspace_id=workspace.project.id,
        mcp_client_manager=manager,
    )


@pytest.mark.asyncio
async def test_a_failed_listing_retires_nothing_and_commits_no_missing_evidence(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    manager = RecordingMcpResourceManager(resource_discovery_error=RuntimeError("handshake reset"))

    with pytest.raises(HTTPException) as failure:
        await _mirror_through_admin(db, workspace, manager)

    assert failure.value.status_code == 502
    assert "resources" in failure.value.detail
    assert "handshake reset" not in failure.value.detail
    assert await _lifecycle_state(db, workspace) == LIFECYCLE_ACTIVE
    assert (await resource_binding(db, workspace, DOC_URI)).is_enabled is True
    assert await _state(db, workspace, kind=MCP_RESOURCE_KIND, identity=resource_id(DOC_URI)) == STATE_ALLOWED


@pytest.mark.asyncio
async def test_a_successful_empty_listing_still_retires_the_catalog(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))

    result = await _mirror_through_admin(db, workspace, RecordingMcpResourceManager())

    assert result["resources"]["missing_entries"] == [resource_id(DOC_URI)]
    assert await _lifecycle_state(db, workspace) == LIFECYCLE_MISSING
    assert (await resource_binding(db, workspace, DOC_URI)).is_enabled is False
    assert (
        await _state(db, workspace, kind=MCP_RESOURCE_KIND, identity=resource_id(DOC_URI)) == STATE_UPSTREAM_MISSING
    )


@pytest.mark.asyncio
async def test_a_capability_the_server_does_not_implement_is_an_empty_success(db) -> None:
    workspace = await create_mcp_workspace(db)
    manager = RecordingMcpResourceManager(
        prompts=[mcp_prompt(PROMPT)],
        resource_discovery_error=_MethodNotFoundError(),
    )

    result = await _mirror_through_admin(db, workspace, manager)

    assert result["resources"]["mirrored"] == 0
    assert result["prompts"]["mirrored"] == 1
    assert (await prompt_binding(db, workspace, PROMPT)).is_enabled is False


@pytest.mark.asyncio
async def test_a_server_without_a_live_session_mirrors_nothing(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    manager = RecordingMcpResourceManager(session_available=False)

    with pytest.raises(HTTPException) as failure:
        await _mirror_through_admin(db, workspace, manager)

    assert failure.value.status_code == 502
    assert await _lifecycle_state(db, workspace) == LIFECYCLE_ACTIVE
