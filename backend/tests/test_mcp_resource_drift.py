"""Contract drift for governed MCP resources and prompts is Workspace-isolated.

``CapabilityType`` is a global catalog row: two workspaces that mirrored the same
server share it. A re-mirror therefore rewrites a contract *every* bound workspace
is governed by, even though it ran in one of them.

That is only safe if drift is decided per workspace. Each binding records the
contract digest its admin approved, and the decision compares that against the
digest the shared catalog currently holds — so the workspace that re-mirrored and
every other affected workspace both fail closed, and each one is released again
only by its own admin accepting the new contract.
"""

from __future__ import annotations

import pytest

from app.services.mcp_resource_admin_policy import guard_mcp_resource_binding_update
from app.services.mcp_resource_identity import MCP_RESOURCE_POLICY_NAME
from app.services.mcp_resource_index import load_mcp_resource_index
from app.services.mcp_resource_policy import decide_mcp_resource
from app.services.mcp_resource_states import STATE_CONTRACT_DRIFT
from app.tools.registry import execute_tool_with_plugins
from tests.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.mcp_resource_support import (
    DOC_URI,
    GET_PROMPT_TOOL,
    PROMPT,
    READ_RESOURCE_TOOL,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mcp_prompt,
    mcp_resource,
    mirror_catalog,
    prompt_binding,
    read_params,
    resource_binding,
    resource_context,
    resource_id,
)


async def _state(db, workspace, *, kind: str, identity: str) -> str:
    index = await load_mcp_resource_index(db, workspace_id=workspace.project.id)
    return decide_mcp_resource(index, kind=kind, server_name=SERVER, identity=identity).state


@pytest.mark.asyncio
async def test_a_mirror_in_one_workspace_fails_the_other_closed(db, monkeypatch) -> None:
    first = await create_mcp_workspace(db)
    second = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    for workspace in (first, second):
        await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
        await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
        await enable_binding(db, await prompt_binding(db, workspace, PROMPT))

    # Only the first workspace re-mirrors, but the CapabilityType it rewrites is
    # the one the second workspace is bound to as well.
    await mirror_catalog(
        db,
        first,
        resources=[mcp_resource(DOC_URI, mime_type="application/pdf")],
        prompts=[mcp_prompt(PROMPT, arguments=[{"name": "topic", "required": False}])],
    )

    for workspace in (first, second):
        read = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))
        rendered = await execute_tool_with_plugins(
            GET_PROMPT_TOOL,
            {"server_name": SERVER, "prompt_name": PROMPT, "arguments": {}},
            resource_context(workspace, db),
        )
        for result in (read, rendered):
            assert result["blocked_by"] == MCP_RESOURCE_POLICY_NAME
            assert result["reason"].endswith("_not_available")
    assert await _state(db, second, kind="mcp_resource", identity=resource_id(DOC_URI)) == STATE_CONTRACT_DRIFT
    assert await _state(db, second, kind="mcp_prompt", identity=PROMPT) == STATE_CONTRACT_DRIFT
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_the_unaffected_workspace_stays_enabled_but_not_executable(db, monkeypatch) -> None:
    """The second workspace's own governance state is never rewritten from outside."""
    first = await create_mcp_workspace(db)
    second = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    for workspace in (first, second):
        await mirror_catalog(db, workspace, resources=[DOC_URI])
        await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk="write", scopes=["change"])

    await mirror_catalog(db, first, resources=[mcp_resource(DOC_URI, mime_type="application/pdf")])

    binding = await resource_binding(db, second, DOC_URI)
    assert binding.is_enabled is True
    assert binding.policy_config["risk"] == "write"
    assert binding.intent_scopes == ["change"]
    # Enabled is not executable: the workspace still fails closed on the digest.
    assert await _state(db, second, kind="mcp_resource", identity=resource_id(DOC_URI)) == STATE_CONTRACT_DRIFT


@pytest.mark.asyncio
async def test_each_workspace_is_released_by_its_own_review(db, monkeypatch) -> None:
    first = await create_mcp_workspace(db)
    second = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    for workspace in (first, second):
        await mirror_catalog(db, workspace, resources=[DOC_URI])
        await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    await mirror_catalog(db, first, resources=[mcp_resource(DOC_URI, mime_type="application/pdf")])

    # Re-enabling through the admin write boundary is the explicit review.
    binding = await resource_binding(db, second, DOC_URI)
    guarded = guard_mcp_resource_binding_update(binding, {"is_enabled": True})
    binding.binding_config = guarded["binding_config"]
    binding.is_enabled = True
    await db.flush()

    reviewed = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(second, db))
    still_parked = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(first, db))

    assert reviewed["contents"][0]["text"] == "# React"
    assert still_parked["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert manager.resource_reads == [(SERVER, DOC_URI)]


@pytest.mark.asyncio
async def test_a_binding_without_an_approved_digest_fails_closed(db, monkeypatch) -> None:
    """A hand-made binding has approved nothing, so it cannot inherit an approval."""
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    binding = await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    binding.binding_config = {key: value for key, value in binding.binding_config.items() if key != "contractDigest"}
    await db.flush()

    result = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))

    assert result["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert await _state(db, workspace, kind="mcp_resource", identity=resource_id(DOC_URI)) == STATE_CONTRACT_DRIFT
