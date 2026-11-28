"""Admin edits of mirrored MCP capability bindings: governance fields may change, capability identity,
schema digest and drift review may not; a new server's tool needs a mirror and an enabled binding."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.workspace_composition.admin_api import update_workspace_binding
from tests.conftest import ADMIN_PASSWORD
from tests.mcp_capability_support import (
    DIRECT_WRITE_TOOL,
    READ_TOOL,
    SERVER,
    WRITE_TOOL,
    RecordingMcpManager,
    capability_binding,
    create_mcp_workspace,
    enable_capability,
    install_mcp_manager,
    mcp_tool,
    mirror_tools,
    register_mcp_server,
)


async def _drifted_workspace(db):
    workspace = await create_mcp_workspace(db)
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="write")
    await mirror_tools(
        db,
        workspace,
        [mcp_tool(WRITE_TOOL, properties={"path": {"type": "string"}, "force": {"type": "boolean"}})],
    )
    await db.commit()
    return workspace


@pytest.mark.asyncio
async def test_enabling_a_binding_through_the_admin_api_clears_the_drift_review(db) -> None:
    workspace = await _drifted_workspace(db)
    binding = await capability_binding(db, workspace, WRITE_TOOL)
    assert binding.binding_config["reviewState"] == "needs_review"

    await update_workspace_binding(
        db,
        workspace_id=workspace.project.id,
        binding_id=binding.id,
        payload={"is_enabled": True},
    )

    binding = await capability_binding(db, workspace, WRITE_TOOL)
    assert binding.is_enabled is True
    assert "reviewState" not in binding.binding_config


@pytest.mark.asyncio
async def test_admin_cannot_retarget_a_mirrored_capability_binding(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_tools(db, workspace, [READ_TOOL, WRITE_TOOL])
    await db.commit()
    binding = await capability_binding(db, workspace, READ_TOOL)

    with pytest.raises(HTTPException) as retarget:
        await update_workspace_binding(
            db,
            workspace_id=workspace.project.id,
            binding_id=binding.id,
            payload={"binding_config": {**binding.binding_config, "toolName": WRITE_TOOL}},
        )
    assert retarget.value.status_code == 400
    assert "toolName" in str(retarget.value.detail)

    with pytest.raises(HTTPException) as reserver:
        await update_workspace_binding(
            db,
            workspace_id=workspace.project.id,
            binding_id=binding.id,
            payload={"binding_config": {**binding.binding_config, "serverName": "other"}},
        )
    assert reserver.value.status_code == 400

    binding = await capability_binding(db, workspace, READ_TOOL)
    assert binding.binding_config["toolName"] == READ_TOOL
    assert binding.binding_config["serverName"] == SERVER


@pytest.mark.asyncio
async def test_admin_cannot_clear_the_drift_review_or_digest_through_binding_config(db) -> None:
    workspace = await _drifted_workspace(db)
    binding = await capability_binding(db, workspace, WRITE_TOOL)
    stored_digest = binding.binding_config["schemaDigest"]

    with pytest.raises(HTTPException) as overwrite:
        await update_workspace_binding(
            db,
            workspace_id=workspace.project.id,
            binding_id=binding.id,
            payload={"binding_config": {**binding.binding_config, "reviewState": "reviewed"}},
        )
    assert overwrite.value.status_code == 400

    # Dropping the key from the mapping does not clear it either: mirror-owned
    # state always comes from the persisted row.
    await update_workspace_binding(
        db,
        workspace_id=workspace.project.id,
        binding_id=binding.id,
        payload={"binding_config": {"note": "reviewed offline"}, "display_name": "Remote write"},
    )

    binding = await capability_binding(db, workspace, WRITE_TOOL)
    assert binding.binding_config["reviewState"] == "needs_review"
    assert binding.binding_config["schemaDigest"] == stored_digest
    assert binding.binding_config["note"] == "reviewed offline"
    assert binding.display_name == "Remote write"
    assert binding.is_enabled is False


@pytest.mark.asyncio
async def test_admin_sets_capability_risk_and_keeps_mirror_provenance(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await db.commit()
    binding = await capability_binding(db, workspace, WRITE_TOOL)

    payload = await update_workspace_binding(
        db,
        workspace_id=workspace.project.id,
        binding_id=binding.id,
        payload={"policy_config": {"risk": "WRITE"}, "is_enabled": True},
    )
    updated = next(item for item in payload["bindings"] if item["id"] == binding.id)
    assert updated["policy_config"]["risk"] == "write"
    assert updated["policy_config"]["source"] == "mcp_capability_mirror"
    assert updated["is_enabled"] is True

    with pytest.raises(HTTPException) as unsupported:
        await update_workspace_binding(
            db,
            workspace_id=workspace.project.id,
            binding_id=binding.id,
            payload={"policy_config": {"risk": "superuser"}},
        )
    assert unsupported.value.status_code == 400

    binding = await capability_binding(db, workspace, WRITE_TOOL)
    assert binding.policy_config["risk"] == "write"


@pytest.mark.asyncio
async def test_admin_api_rejects_a_capability_retarget_over_http(client, db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await db.commit()
    binding = await capability_binding(db, workspace, WRITE_TOOL)

    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303

    response = await client.put(
        f"/admin/chat/api/panel/projects/{workspace.project.id}/workspace-composition/bindings/{binding.id}",
        json={"binding_config": {**binding.binding_config, "schemaDigest": "forged"}},
    )
    assert response.status_code == 400, response.text
    assert "schemaDigest" in response.text

    binding = await capability_binding(db, workspace, WRITE_TOOL)
    assert binding.binding_config["schemaDigest"] != "forged"


@pytest.mark.asyncio
async def test_a_new_tool_becomes_usable_only_through_the_admin_mirror_and_enable_path(client, db, monkeypatch):
    from app.tools.registry import execute_tool_with_plugins

    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await register_mcp_server(db, workspace)
    await db.commit()
    context = workspace.context(db)
    guarded = workspace.context(db, approval_policy={"require_for_risks": ["write"]})
    denied = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    assert denied["reason"] == "mcp_capability_not_bound"

    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    mirrored = await client.post(f"/admin/chat/api/panel/mcp/servers/{SERVER}/mirror-capabilities",
                                 json={"workspace_id": workspace.project.id, "auto_connect": True})
    assert mirrored.status_code == 200, mirrored.text
    assert mirrored.json()["added"] == 1
    db.expire_all()
    await db.refresh(workspace.project)
    still = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    assert still["reason"] == "mcp_capability_disabled"  # mirrored bindings start disabled

    binding = await capability_binding(db, workspace, WRITE_TOOL)
    enabled = await client.put(
        f"/admin/chat/api/panel/projects/{workspace.project.id}/workspace-composition/bindings/{binding.id}",
        json={"is_enabled": True, "policy_config": {"risk": "write"}},
    )
    assert enabled.status_code == 200, enabled.text
    db.expire_all()
    await db.refresh(workspace.project)
    assert (await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)).get("success") is True
    assert manager.calls == [(SERVER, WRITE_TOOL, {"path": "a"})]

    pending = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "b"}, guarded)
    assert pending["approval_required"] is True
    assert manager.calls == [(SERVER, WRITE_TOOL, {"path": "a"})]
