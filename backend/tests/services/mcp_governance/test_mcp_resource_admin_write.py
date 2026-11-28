"""Admin edits of mirrored MCP resource and prompt bindings."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.mcp_governance.resource_identity import (
    LIFECYCLE_MISSING,
    MCP_RESOURCE_KIND,
    MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW,
    mcp_resource_server_marker_key,
)
from app.services.workspace_composition.admin_api import update_workspace_binding
from tests.conftest import ADMIN_PASSWORD
from tests.support.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.support.mcp_resource_support import (
    DOC_URI,
    OTHER_URI,
    PROMPT,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mcp_prompt,
    mcp_resource,
    mirror_catalog,
    prompt_binding,
    register_mcp_server,
    resource_binding,
)


async def _drifted_resource(db):
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk="read")
    await mirror_catalog(db, workspace, resources=[mcp_resource(DOC_URI, mime_type="application/pdf")])
    await db.commit()
    return workspace


async def _update(db, workspace, binding, payload):
    return await update_workspace_binding(
        db,
        workspace_id=workspace.project.id,
        binding_id=binding.id,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_enabling_a_drifted_resource_clears_its_contract_review(db) -> None:
    workspace = await _drifted_resource(db)
    binding = await resource_binding(db, workspace, DOC_URI)
    assert binding.binding_config["reviewState"] == MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW

    await _update(db, workspace, binding, {"is_enabled": True, "binding_config": dict(binding.binding_config)})

    refreshed = await resource_binding(db, workspace, DOC_URI)
    assert refreshed.is_enabled is True
    assert "reviewState" not in refreshed.binding_config
    assert refreshed.binding_config["acknowledgedContractDigest"] == refreshed.binding_config["contractDigest"]


@pytest.mark.asyncio
async def test_a_binding_cannot_be_retargeted_onto_another_resource(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI, OTHER_URI])
    binding = await resource_binding(db, workspace, DOC_URI)

    with pytest.raises(HTTPException) as retarget:
        await _update(
            db,
            workspace,
            binding,
            {"binding_config": {**binding.binding_config, "resourceUri": OTHER_URI}},
        )
    with pytest.raises(HTTPException) as forged_digest:
        await _update(
            db,
            workspace,
            binding,
            {"binding_config": {**binding.binding_config, "contractDigest": "0" * 64}},
        )

    assert retarget.value.status_code == 400
    assert forged_digest.value.status_code == 400


@pytest.mark.asyncio
async def test_a_drift_review_survives_every_edit_that_is_not_enabling(db) -> None:
    workspace = await _drifted_resource(db)
    binding = await resource_binding(db, workspace, DOC_URI)
    stripped = {key: value for key, value in binding.binding_config.items() if key != "reviewState"}

    await _update(db, workspace, binding, {"binding_config": stripped, "display_name": "Docs"})
    with pytest.raises(HTTPException) as error:
        await _update(
            db,
            workspace,
            binding,
            {"binding_config": {**binding.binding_config, "reviewState": "reviewed"}},
        )

    assert error.value.status_code == 400
    refreshed = await resource_binding(db, workspace, DOC_URI)
    assert refreshed.display_name == "Docs"
    assert refreshed.is_enabled is False
    assert refreshed.binding_config["reviewState"] == MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW


@pytest.mark.asyncio
async def test_the_upstream_lifecycle_is_not_an_admin_field(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    await mirror_catalog(db, workspace, resources=[])
    await db.commit()
    binding = await resource_binding(db, workspace, DOC_URI)

    with pytest.raises(HTTPException) as revived:
        await _update(
            db,
            workspace,
            binding,
            {"binding_config": {**binding.binding_config, "lifecycleState": "active"}},
        )
    await _update(db, workspace, binding, {"is_enabled": True})

    refreshed = await resource_binding(db, workspace, DOC_URI)
    assert revived.value.status_code == 400
    assert refreshed.is_enabled is True
    assert refreshed.binding_config["lifecycleState"] == LIFECYCLE_MISSING


@pytest.mark.asyncio
async def test_a_mirror_history_marker_is_not_editable(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await db.commit()
    workspace_bindings = await _loaded_bindings(db, workspace)
    marker = workspace_bindings[mcp_resource_server_marker_key(MCP_RESOURCE_KIND, SERVER)]

    with pytest.raises(HTTPException) as error:
        await _update(db, workspace, marker, {"is_enabled": True})

    assert error.value.status_code == 400


async def _loaded_bindings(db, workspace) -> dict:
    from sqlalchemy import select

    from app.models import WorkspaceCapabilityBinding

    rows = (
        (
            await db.execute(
                select(WorkspaceCapabilityBinding).where(
                    WorkspaceCapabilityBinding.workspace_id == workspace.project.id
                )
            )
        )
        .scalars()
        .all()
    )
    return {str(row.binding_key): row for row in rows}


@pytest.mark.asyncio
async def test_risk_must_come_from_the_allow_list(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, prompts=[PROMPT])
    binding = await prompt_binding(db, workspace, PROMPT)

    with pytest.raises(HTTPException) as error:
        await _update(db, workspace, binding, {"policy_config": {**binding.policy_config, "risk": "harmless"}})
    await _update(db, workspace, binding, {"policy_config": {**binding.policy_config, "risk": "ADMIN"}})

    assert error.value.status_code == 400
    refreshed = await prompt_binding(db, workspace, PROMPT)
    assert refreshed.policy_config["risk"] == "admin"


@pytest.mark.asyncio
async def test_the_round_trip_the_admin_ui_sends_keeps_working(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, prompts=[mcp_prompt(PROMPT)])
    binding = await prompt_binding(db, workspace, PROMPT)

    await _update(
        db,
        workspace,
        binding,
        {
            "is_enabled": True,
            "display_name": "Summarize docs",
            "intent_scopes": ["knowledge"],
            "binding_config": dict(binding.binding_config),
            "policy_config": {**binding.policy_config, "risk": "read"},
        },
    )

    refreshed = await prompt_binding(db, workspace, PROMPT)
    assert refreshed.is_enabled is True
    assert refreshed.display_name == "Summarize docs"
    assert refreshed.intent_scopes == ["knowledge"]
    assert refreshed.binding_config["promptName"] == PROMPT
    assert refreshed.policy_config["source"] == "mcp_resource_mirror"


@pytest.mark.asyncio
async def test_the_admin_mirror_endpoint_populates_a_disabled_catalog_over_http(client, db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    await register_mcp_server(db, workspace)
    await db.commit()
    install_mcp_manager(
        monkeypatch,
        RecordingMcpResourceManager(
            resources=[mcp_resource(DOC_URI)],
            prompts=[mcp_prompt(PROMPT)],
            connection_persists=True,
        ),
    )

    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303

    response = await client.post(
        f"/admin/chat/api/panel/mcp/servers/{SERVER}/mirror-resources",
        json={"workspace_id": workspace.project.id},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["server"] == SERVER
    assert payload["resources"]["added"] == 1
    assert payload["prompts"]["added"] == 1
    assert (await resource_binding(db, workspace, DOC_URI)).is_enabled is False
    assert (await prompt_binding(db, workspace, PROMPT)).is_enabled is False


@pytest.mark.asyncio
async def test_the_admin_mirror_endpoint_requires_authentication(client, db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    await db.commit()
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager(resources=[mcp_resource(DOC_URI)]))

    response = await client.post(
        f"/admin/chat/api/panel/mcp/servers/{SERVER}/mirror-resources",
        json={"workspace_id": workspace.project.id},
    )

    assert response.status_code in {401, 403}, response.text
