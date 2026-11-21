"""MCP registry checks run before transport: a missing or expired secret, server governance and a disabled mirrored capability deny, connect resolves the secret only into ephemeral config, and activation changes are revised and audited."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ComplianceAuditRecord, McpServerRegistration
from app.services.mcp_capability_catalog import mirror_mcp_server_capabilities
from app.services.mcp_server_registry_connections import connect_mcp_server
from app.services.mcp_server_registry_queries import list_mcp_servers
from app.services.mcp_server_registry_writes import install_catalog_mcp_server, update_mcp_server
from app.time_utils import utc_now
from tests.mcp_server_registry_support import CATALOG, FakeMcpClientManager, _context7_secret, _workspace


@pytest.mark.asyncio
async def test_missing_or_expired_secret_denies_before_transport(db):
    workspace = await _workspace(db)
    secret = await _context7_secret(db, workspace)
    secret.expires_at = utc_now() - timedelta(minutes=1)
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
    manager = FakeMcpClientManager()

    with pytest.raises(HTTPException) as blocked:
        await connect_mcp_server(
            db,
            name="context7",
            workspace_id=workspace.id,
            catalog=CATALOG,
            actor_user_id=None,
            mcp_client_manager=manager,
        )

    assert blocked.value.status_code == 409
    assert "missing_or_invalid_secret_reference" in str(blocked.value.detail)
    assert manager.registered == []
    assert manager.connect_calls == []


@pytest.mark.asyncio
async def test_server_governance_denies_before_transport(db):
    workspace = await _workspace(db, enabled=False)
    secret = await _context7_secret(db, workspace)
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
    manager = FakeMcpClientManager()

    with pytest.raises(HTTPException) as blocked:
        await connect_mcp_server(
            db,
            name="context7",
            workspace_id=workspace.id,
            catalog=CATALOG,
            actor_user_id=None,
            mcp_client_manager=manager,
        )

    assert blocked.value.status_code == 409
    assert "mcp_server_not_active_for_project" in str(blocked.value.detail)
    assert manager.registered == []
    assert manager.connect_calls == []


@pytest.mark.asyncio
async def test_a_server_without_an_enabled_capability_still_connects_for_its_catalog(db):
    """Connecting lists the catalog an admin mirrors and enables; each tool call is decided per capability."""
    workspace = await _workspace(db)
    secret = await _context7_secret(db, workspace)
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
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=workspace.id,
        server_name="context7",
        tools=[
            SimpleNamespace(
                name="query-docs",
                description="Read documentation",
                input_schema={"type": "object", "properties": {}},
            )
        ],
    )
    await db.commit()
    manager = FakeMcpClientManager()

    connected = await connect_mcp_server(
        db,
        name="context7",
        workspace_id=workspace.id,
        catalog=CATALOG,
        actor_user_id=None,
        mcp_client_manager=manager,
    )

    assert connected["connected"] is True
    assert connected["capability_governance"] == "no_enabled_capability"
    assert manager.connect_calls == ["context7"]


@pytest.mark.asyncio
async def test_connect_resolves_secret_only_into_ephemeral_runtime_config(db):
    workspace = await _workspace(db)
    secret = await _context7_secret(db, workspace)
    registration = await install_catalog_mcp_server(
        db,
        slug="context7",
        body={
            "owner_scope": "workspace",
            "workspace_id": workspace.id,
            "is_active": True,
            "secret_refs": {"context7_api_key": f"secret:{secret.id}"},
        },
        catalog=CATALOG,
        actor_user_id=None,
    )
    manager = FakeMcpClientManager()

    result = await connect_mcp_server(
        db,
        name="context7",
        workspace_id=workspace.id,
        catalog=CATALOG,
        actor_user_id=None,
        mcp_client_manager=manager,
    )
    public_rows = await list_mcp_servers(db, workspace_id=workspace.id, mcp_client_manager=manager)

    assert result["connected"] is True
    assert manager.registered[0].headers["CONTEXT7_API_KEY"] == "must-never-leave-runtime-config"
    assert public_rows[0]["secret_fields"] == ["context7_api_key"]
    public_json = json.dumps(public_rows)
    assert secret.id not in public_json
    assert "must-never-leave-runtime-config" not in public_json

    audits = (
        (
            await db.execute(
                select(ComplianceAuditRecord).where(
                    ComplianceAuditRecord.resource_id == registration.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert {row.details["action"] for row in audits} == {"created", "connected"}
    assert "must-never-leave-runtime-config" not in json.dumps([row.details for row in audits])


@pytest.mark.asyncio
async def test_activation_change_is_revised_and_audited(db):
    workspace = await _workspace(db)
    manager = FakeMcpClientManager()
    registration = McpServerRegistration(
        name=f"remote-{uuid.uuid4().hex[:8]}",
        owner_scope="workspace",
        workspace_id=workspace.id,
        transport="streamable-http",
        url="https://example.test/mcp",
        is_active=False,
        settings_json={},
        args_json=[],
    )
    db.add(registration)
    await db.commit()

    updated = await update_mcp_server(
        db,
        name=registration.name,
        workspace_id=workspace.id,
        body={"is_active": True},
        catalog=CATALOG,
        actor_user_id=None,
        mcp_client_manager=manager,
    )

    assert updated.is_active is True
    assert updated.revision == 2
    audit = (
        await db.execute(
            select(ComplianceAuditRecord).where(ComplianceAuditRecord.resource_id == registration.id)
        )
    ).scalar_one()
    assert audit.details["action"] == "activation_changed"
