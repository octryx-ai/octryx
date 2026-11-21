"""MCP servers are scoped per workspace: cross-workspace use and wrong secret scopes are rejected, one name stays independent per workspace, and a live runtime name conflict denies without replacing."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.services.mcp_server_registry import get_scoped_registration
from app.services.mcp_server_registry_connections import connect_mcp_server
from app.services.mcp_server_registry_writes import install_catalog_mcp_server
from tests.mcp_server_registry_support import CATALOG, FakeMcpClientManager, _context7_secret, _workspace


@pytest.mark.asyncio
async def test_registry_rejects_cross_workspace_and_wrong_secret_scope(db):
    owner = await _workspace(db)
    other = await _workspace(db)
    other_secret = await _context7_secret(db, other)

    with pytest.raises(HTTPException) as wrong_scope:
        await install_catalog_mcp_server(
            db,
            slug="context7",
            body={
                "owner_scope": "workspace",
                "workspace_id": owner.id,
                "is_active": True,
                "secret_refs": {"context7_api_key": f"secret:{other_secret.id}"},
            },
            catalog=CATALOG,
            actor_user_id=None,
        )
    assert wrong_scope.value.status_code == 400

    owner_secret = await _context7_secret(db, owner)
    await install_catalog_mcp_server(
        db,
        slug="context7",
        body={
            "owner_scope": "workspace",
            "workspace_id": owner.id,
            "is_active": True,
            "secret_refs": {"context7_api_key": owner_secret.id},
        },
        catalog=CATALOG,
        actor_user_id=None,
    )

    with pytest.raises(HTTPException) as cross_workspace:
        await get_scoped_registration(db, name="context7", workspace_id=other.id)
    assert cross_workspace.value.status_code == 404


@pytest.mark.asyncio
async def test_same_server_name_remains_independently_scoped_per_workspace(db):
    first = await _workspace(db)
    second = await _workspace(db)
    first_secret = await _context7_secret(db, first)
    second_secret = await _context7_secret(db, second)

    first_registration = await install_catalog_mcp_server(
        db,
        slug="context7",
        body={
            "owner_scope": "workspace",
            "workspace_id": first.id,
            "is_active": True,
            "secret_refs": {"context7_api_key": first_secret.id},
        },
        catalog=CATALOG,
        actor_user_id=None,
    )
    second_registration = await install_catalog_mcp_server(
        db,
        slug="context7",
        body={
            "owner_scope": "workspace",
            "workspace_id": second.id,
            "is_active": True,
            "secret_refs": {"context7_api_key": second_secret.id},
        },
        catalog=CATALOG,
        actor_user_id=None,
    )

    assert first_registration.id != second_registration.id
    assert (await get_scoped_registration(db, name="context7", workspace_id=first.id)).id == first_registration.id
    assert (await get_scoped_registration(db, name="context7", workspace_id=second.id)).id == second_registration.id


@pytest.mark.asyncio
async def test_live_runtime_name_conflict_denies_without_replacing_another_workspace(db):
    first = await _workspace(db)
    second = await _workspace(db)
    first_secret = await _context7_secret(db, first, value="first-workspace-secret")
    second_secret = await _context7_secret(db, second, value="second-workspace-secret")
    registrations = []
    for workspace, secret in ((first, first_secret), (second, second_secret)):
        registrations.append(
            await install_catalog_mcp_server(
                db,
                slug="context7",
                body={
                    "owner_scope": "workspace",
                    "workspace_id": workspace.id,
                    "is_active": True,
                    "secret_refs": {"context7_api_key": secret.id},
                },
                catalog=CATALOG,
                actor_user_id=None,
            )
        )
    manager = FakeMcpClientManager()
    await connect_mcp_server(
        db,
        name="context7",
        workspace_id=first.id,
        catalog=CATALOG,
        actor_user_id=None,
        mcp_client_manager=manager,
    )

    with pytest.raises(HTTPException) as conflict:
        await connect_mcp_server(
            db,
            name="context7",
            workspace_id=second.id,
            catalog=CATALOG,
            actor_user_id=None,
            mcp_client_manager=manager,
        )

    assert conflict.value.status_code == 409
    assert "ownership scope" in str(conflict.value.detail)
    assert manager.registered[-1].metadata["registry_id"] == registrations[0].id
    assert manager.registered[-1].headers["CONTEXT7_API_KEY"] == "first-workspace-secret"
    assert "second-workspace-secret" not in json.dumps(manager.registered[-1].to_dict())
