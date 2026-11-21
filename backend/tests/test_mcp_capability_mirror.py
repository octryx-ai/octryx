"""Mirror writes for MCP capabilities.

What the mirror is allowed to write into the Workspace Capability catalog:
disabled-by-default bindings, an idempotent re-mirror, persisted schema drift,
rejected ambiguous or oversized identifiers, a redacted contract, one canonical
(casefolded) server identity, and never a reactivation of a retired capability.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import CapabilityType, WorkspaceCapabilityBinding
from app.services.mcp_capability_policy import (
    MCP_CAPABILITY_KIND,
    mcp_capability_binding_key,
)
from tests.mcp_capability_support import (
    READ_TOOL,
    SERVER,
    WRITE_TOOL,
    capability_binding,
    create_mcp_workspace,
    enable_capability,
    mcp_tool,
    mirror_tools,
)


@pytest.mark.asyncio
async def test_mirror_creates_disabled_bindings_and_is_idempotent(db) -> None:
    workspace = await create_mcp_workspace(db)
    tools = [mcp_tool(READ_TOOL), mcp_tool(WRITE_TOOL)]

    first = await mirror_tools(db, workspace, tools)
    assert first == {
        "server": SERVER,
        "mirrored": 2,
        "added": 2,
        "updated": 0,
        "drifted": 0,
        "drifted_capabilities": [],
        "rejected_capabilities": [],
        "inactive_capabilities": [],
    }

    capability_types = (
        (await db.execute(select(CapabilityType).where(CapabilityType.kind == MCP_CAPABILITY_KIND))).scalars().all()
    )
    assert {row.key for row in capability_types} == {
        mcp_capability_binding_key(SERVER, READ_TOOL),
        mcp_capability_binding_key(SERVER, WRITE_TOOL),
    }

    bindings = (
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
    capability_bindings = list(bindings)
    assert len(capability_bindings) == 2
    assert all(binding.capability_kind == MCP_CAPABILITY_KIND for binding in bindings)
    assert all(binding.is_enabled is False and binding.is_default is False for binding in bindings)
    assert all(binding.policy_config["risk"] == "unknown" for binding in capability_bindings)

    again = await mirror_tools(db, workspace, tools)
    assert again["added"] == 0
    assert again["updated"] == 0
    assert again["drifted"] == 0


@pytest.mark.asyncio
async def test_mirror_rejects_identifiers_that_would_share_a_catalog_key(db) -> None:
    workspace = await create_mcp_workspace(db)

    result = await mirror_tools(db, workspace, [READ_TOOL, "scope:write"])
    assert result["mirrored"] == 1
    assert result["rejected_capabilities"] == ["scope:write"]

    with pytest.raises(ValueError):
        await mirror_tools(db, workspace, [READ_TOOL], server_name="demo__two")


@pytest.mark.asyncio
async def test_overlong_capability_identifiers_are_rejected_before_any_write(db) -> None:
    workspace = await create_mcp_workspace(db)
    overlong = "t" * 200

    result = await mirror_tools(db, workspace, [READ_TOOL, overlong])
    assert result["mirrored"] == 1
    assert result["rejected_capabilities"] == [overlong]

    bindings = (
        (
            await db.execute(
                select(WorkspaceCapabilityBinding).where(
                    WorkspaceCapabilityBinding.workspace_id == workspace.project.id,
                    WorkspaceCapabilityBinding.capability_kind == MCP_CAPABILITY_KIND,
                )
            )
        )
        .scalars()
        .all()
    )
    assert all(len(str(binding.binding_key)) <= 200 for binding in bindings)
    assert all(len(str(binding.source_entity_id or "")) <= 120 for binding in bindings)

    with pytest.raises(ValueError):
        await mirror_tools(db, workspace, [READ_TOOL], server_name="s" * 200)


@pytest.mark.asyncio
async def test_remirror_flags_schema_drift_and_keeps_admin_governance_state(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_tools(db, workspace, [WRITE_TOOL])
    binding = await enable_capability(db, workspace, WRITE_TOOL, risk="write")
    original_digest = binding.binding_config["schemaDigest"]

    drifted = await mirror_tools(
        db,
        workspace,
        [mcp_tool(WRITE_TOOL, properties={"path": {"type": "string"}, "force": {"type": "boolean"}})],
    )
    assert drifted["updated"] == 1
    assert drifted["drifted"] == 1
    assert drifted["drifted_capabilities"] == [WRITE_TOOL]

    binding = await capability_binding(db, workspace, WRITE_TOOL)
    assert binding.binding_config["previousSchemaDigest"] == original_digest
    assert binding.binding_config["schemaDigest"] != original_digest
    # Drift is a persisted state, not a one-response counter: the approved
    # contract is gone, so the capability is parked until an admin reviews it.
    assert binding.binding_config["reviewState"] == "needs_review"
    assert binding.is_enabled is False
    # Other admin-owned governance state survives a re-mirror.
    assert binding.policy_config["risk"] == "write"


@pytest.mark.asyncio
async def test_remirror_never_reactivates_a_retired_capability_type(db) -> None:
    """A globally retired capability stays retired, so a re-mirror cannot widen execution."""
    workspace = await create_mcp_workspace(db)
    await mirror_tools(db, workspace, [WRITE_TOOL])
    binding = await capability_binding(db, workspace, WRITE_TOOL)
    binding.capability_type.is_active = False
    binding.capability_type.lifecycle_status = "retired"
    binding.is_enabled = True
    await db.flush()

    result = await mirror_tools(
        db,
        workspace,
        [mcp_tool(WRITE_TOOL, description="a refreshed description")],
    )
    assert result["inactive_capabilities"] == [WRITE_TOOL]

    binding = await capability_binding(db, workspace, WRITE_TOOL)
    assert binding.capability_type.is_active is False
    assert binding.capability_type.lifecycle_status == "retired"
    # The contract still refreshes; only the lifecycle decision is untouched.
    assert binding.capability_type.description == "a refreshed description"


@pytest.mark.asyncio
async def test_mirror_normalizes_the_server_name_to_one_canonical_identity(db) -> None:
    """A case variant of a server name is the same server, not a second catalog."""
    workspace = await create_mcp_workspace(db)

    first = await mirror_tools(db, workspace, [WRITE_TOOL], server_name="Demo")
    assert first["server"] == SERVER
    assert first["added"] == 1

    binding = await capability_binding(db, workspace, WRITE_TOOL)
    assert binding.binding_key == mcp_capability_binding_key(SERVER, WRITE_TOOL)
    assert binding.binding_config["serverName"] == SERVER

    again = await mirror_tools(db, workspace, [WRITE_TOOL], server_name="DEMO")
    assert again["added"] == 0
    assert again["updated"] == 0


@pytest.mark.asyncio
async def test_mirrored_contract_is_redacted_and_carries_no_connection_material(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_tools(
        db,
        workspace,
        [
            mcp_tool(
                READ_TOOL,
                description="Call with Authorization: Bearer abcdef1234567890 to authenticate.",
                properties={"token": {"type": "string", "description": "api_key=super-secret-value"}},
            )
        ],
    )
    capability_type = (
        await db.execute(
            select(CapabilityType).where(CapabilityType.key == mcp_capability_binding_key(SERVER, READ_TOOL))
        )
    ).scalar_one()
    contract = capability_type.contract

    assert set(contract) == {
        "sourceEntityType",
        "sourceEntityId",
        "serverName",
        "toolName",
        "description",
        "inputSchema",
        "schemaDigest",
    }
    assert "abcdef1234567890" not in contract["description"]
    assert "[redacted]" in contract["description"]
    assert "super-secret-value" not in contract["inputSchema"]["properties"]["token"]["description"]
