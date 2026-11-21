"""Catalog writes for governed MCP resources and prompts.

The mirror is the only author of a governed item's identity, so these tests pin
what it writes, what it refuses to write, and what it must never rewrite on a
re-run: a raw URI is never persisted, a retired item is never reactivated, and a
real contract change parks the binding in an explicit review state instead of
silently widening an approved contract.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import CapabilityType, WorkspaceCapabilityBinding
from app.services.mcp_resource_identity import (
    MCP_PROMPT_KIND,
    MCP_RESOURCE_KIND,
    MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW,
    mcp_resource_server_marker_key,
)
from tests.mcp_resource_support import (
    DOC_URI,
    OTHER_URI,
    POSTGRES_URI,
    PROMPT,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mcp_prompt,
    mcp_resource,
    mirror_catalog,
    prompt_binding,
    resource_binding,
    resource_id,
)


@pytest.mark.asyncio
async def test_first_mirror_creates_disabled_bindings_and_history_markers(db) -> None:
    workspace = await create_mcp_workspace(db)

    result = await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])

    assert result["server"] == SERVER
    assert result["resources"]["added"] == 1
    assert result["prompts"]["added"] == 1
    assert result["resources"]["mirror_history_recorded"] is True
    resource = await resource_binding(db, workspace, DOC_URI)
    prompt = await prompt_binding(db, workspace, PROMPT)
    assert resource.capability_kind == MCP_RESOURCE_KIND
    assert prompt.capability_kind == MCP_PROMPT_KIND
    for binding in (resource, prompt):
        assert binding.is_enabled is False
        assert binding.is_default is False
        assert binding.policy_config["risk"] == "unknown"
    assert resource.binding_config["resourceUri"] == DOC_URI
    assert prompt.binding_config["promptName"] == PROMPT
    markers = {
        row.binding_key
        for row in (
            await db.execute(
                select(WorkspaceCapabilityBinding).where(
                    WorkspaceCapabilityBinding.workspace_id == workspace.project.id,
                    WorkspaceCapabilityBinding.binding_status == "hidden",
                )
            )
        )
        .scalars()
        .all()
    }
    assert markers == {
        mcp_resource_server_marker_key(MCP_RESOURCE_KIND, SERVER),
        mcp_resource_server_marker_key(MCP_PROMPT_KIND, SERVER),
    }


@pytest.mark.asyncio
async def test_re_mirror_is_idempotent_and_keeps_admin_governance_state(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk="write", scopes=["change"])

    result = await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])

    assert result["resources"] == {
        "mirrored": 1,
        "added": 0,
        "updated": 0,
        "drifted": 0,
        "drifted_entries": [],
        "rejected_entries": [],
        "preserved_entries": [],
        "inactive_entries": [],
        "missing_entries": [],
        "reappeared_entries": [],
        "mirror_history_recorded": False,
    }
    binding = await resource_binding(db, workspace, DOC_URI)
    assert binding.is_enabled is True
    assert binding.policy_config["risk"] == "write"
    assert binding.intent_scopes == ["change"]


@pytest.mark.asyncio
async def test_description_change_alone_is_not_contract_drift(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[mcp_resource(DOC_URI, description="first")])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))

    result = await mirror_catalog(db, workspace, resources=[mcp_resource(DOC_URI, description="second")])

    assert result["resources"]["drifted"] == 0
    binding = await resource_binding(db, workspace, DOC_URI)
    assert binding.is_enabled is True
    assert "reviewState" not in binding.binding_config


@pytest.mark.asyncio
async def test_media_type_and_prompt_argument_drift_park_the_binding_for_review(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT))

    result = await mirror_catalog(
        db,
        workspace,
        resources=[mcp_resource(DOC_URI, mime_type="application/pdf")],
        prompts=[mcp_prompt(PROMPT, arguments=[{"name": "topic", "required": False}])],
    )

    assert result["resources"]["drifted_entries"] == [resource_id(DOC_URI)]
    assert result["prompts"]["drifted_entries"] == [PROMPT]
    for binding in (await resource_binding(db, workspace, DOC_URI), await prompt_binding(db, workspace, PROMPT)):
        assert binding.is_enabled is False
        assert binding.binding_config["reviewState"] == MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW
        assert binding.binding_config["previousContractDigest"]


@pytest.mark.asyncio
async def test_re_mirror_never_reactivates_a_retired_catalog_entry(db) -> None:
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    binding = await resource_binding(db, workspace, DOC_URI)
    capability_type = (
        await db.execute(select(CapabilityType).where(CapabilityType.id == binding.capability_type_id))
    ).scalar_one()
    capability_type.is_active = False
    await db.flush()

    result = await mirror_catalog(db, workspace, resources=[DOC_URI])

    assert result["resources"]["inactive_entries"] == [resource_id(DOC_URI)]
    assert capability_type.is_active is False


@pytest.mark.asyncio
async def test_a_refused_item_never_retires_the_binding_an_admin_approved(db) -> None:
    """Seen-and-refused is not absent.

    A mirror run retires what it did not see. A provider that puts a credential
    into a *description* is still advertising the item, so treating the refusal as
    absence would disable a binding an admin approved — a remote server could
    revoke its own governance by editing prose. The refusal is recorded
    distinctly instead and the prior lifecycle stands.
    """
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk="read", scopes=["diagnosis"])
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT))

    result = await mirror_catalog(
        db,
        workspace,
        resources=[mcp_resource(DOC_URI, description=f"Now served from {POSTGRES_URI}")],
        prompts=[mcp_prompt(PROMPT, description=f"See {POSTGRES_URI}")],
    )

    assert result["resources"]["rejected_entries"] == ["[description:uri_userinfo]"]
    assert result["resources"]["missing_entries"] == []
    assert result["resources"]["preserved_entries"] == [resource_id(DOC_URI)]
    assert result["prompts"]["missing_entries"] == []
    assert result["prompts"]["preserved_entries"] == [PROMPT]
    assert "s3cr3t-token" not in str(result)

    binding = await resource_binding(db, workspace, DOC_URI)
    assert binding.is_enabled is True
    assert binding.intent_scopes == ["diagnosis"]
    assert binding.binding_config["lifecycleState"] == "active"
    assert binding.binding_config["mirrorRejection"]["reason"] == "description:uri_userinfo"
    assert "s3cr3t-token" not in str(binding.binding_config)
    # The refused description was never persisted either.
    assert "s3cr3t-token" not in str((await resource_binding(db, workspace, DOC_URI)).capability_type.contract)

    # A run that accepts the item again clears the marker.
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    binding = await resource_binding(db, workspace, DOC_URI)
    assert "mirrorRejection" not in binding.binding_config
    assert binding.is_enabled is True


@pytest.mark.asyncio
async def test_a_genuinely_absent_item_is_still_retired(db) -> None:
    """The preservation rule must not weaken the missing-item lifecycle."""
    workspace = await create_mcp_workspace(db)
    await mirror_catalog(db, workspace, resources=[DOC_URI, OTHER_URI])
    await enable_binding(db, await resource_binding(db, workspace, OTHER_URI))

    result = await mirror_catalog(
        db,
        workspace,
        resources=[mcp_resource(DOC_URI, description=f"Now served from {POSTGRES_URI}")],
    )

    assert result["resources"]["missing_entries"] == [resource_id(OTHER_URI)]
    assert result["resources"]["preserved_entries"] == [resource_id(DOC_URI)]
    gone = await resource_binding(db, workspace, OTHER_URI)
    assert gone.is_enabled is False
    assert gone.binding_config["lifecycleState"] == "missing"
