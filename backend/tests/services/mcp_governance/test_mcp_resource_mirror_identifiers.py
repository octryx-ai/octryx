"""The mirror refuses credential-bearing URIs and metadata, unaddressable identifiers and server names, and hostile prompt names."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

from app.models import WorkspaceCapabilityBinding
from app.services.mcp_governance.resource_contract import MAX_MCP_RESOURCE_URI_CHARS
from app.services.mcp_governance.resource_identity import MCP_RESOURCE_KIND
from tests.support.mcp_resource_support import (
    CREDENTIAL_URIS,
    DOC_URI,
    OTHER_PROMPT,
    OTHER_URI,
    POSTGRES_URI,
    PRESIGNED_URI,
    PROMPT,
    create_mcp_workspace,
    mcp_prompt,
    mcp_resource,
    mirror_catalog,
    prompt_binding,
    resource_binding,
)


@pytest.mark.asyncio
async def test_a_credential_bearing_uri_is_refused_instead_of_redacted(db) -> None:
    workspace = await create_mcp_workspace(db)

    result = await mirror_catalog(db, workspace, resources=[*CREDENTIAL_URIS, DOC_URI])

    assert result["resources"]["mirrored"] == 1
    assert result["resources"]["rejected_entries"] == sorted(
        ["[uri_credential_query_parameter]", "[uri_userinfo]", "[uri_userinfo]"]
    )
    assert "s3cr3t-token" not in str(result)
    rows = (
        (
            await db.execute(
                select(WorkspaceCapabilityBinding).where(
                    WorkspaceCapabilityBinding.workspace_id == workspace.project.id,
                    WorkspaceCapabilityBinding.capability_kind == MCP_RESOURCE_KIND,
                )
            )
        )
        .scalars()
        .all()
    )
    stored = [row.binding_config for row in rows] + [row.display_name for row in rows]
    assert "s3cr3t-token" not in str(stored)
    assert "internal" not in str(stored)
    for uri in CREDENTIAL_URIS:
        with pytest.raises(NoResultFound):
            await resource_binding(db, workspace, uri)


@pytest.mark.asyncio
async def test_unaddressable_identifiers_are_rejected_before_any_write(db) -> None:
    workspace = await create_mcp_workspace(db)

    result = await mirror_catalog(
        db,
        workspace,
        resources=[mcp_resource("docs://" + "x" * MAX_MCP_RESOURCE_URI_CHARS), DOC_URI],
        prompts=[mcp_prompt("summarize__docs"), PROMPT],
    )

    assert result["resources"]["mirrored"] == 1
    assert result["prompts"]["mirrored"] == 1
    assert result["resources"]["rejected_entries"] == ["[uri_too_long]"]
    assert result["prompts"]["rejected_entries"] == ["[ambiguous_prompt_name]"]
    assert "summarize__docs" not in str(result)
    assert "docs://" not in str(result)
    await resource_binding(db, workspace, DOC_URI)
    await prompt_binding(db, workspace, PROMPT)


@pytest.mark.asyncio
async def test_two_workspaces_keep_independent_catalogs_for_one_server(db) -> None:
    first = await create_mcp_workspace(db)
    second = await create_mcp_workspace(db)

    await mirror_catalog(db, first, resources=[DOC_URI])
    await mirror_catalog(db, second, resources=[OTHER_URI])

    await resource_binding(db, first, DOC_URI)
    await resource_binding(db, second, OTHER_URI)
    with pytest.raises(NoResultFound):
        await resource_binding(db, first, OTHER_URI)


@pytest.mark.asyncio
async def test_an_unaddressable_server_name_is_refused(db) -> None:
    workspace = await create_mcp_workspace(db)

    with pytest.raises(ValueError):
        await mirror_catalog(db, workspace, resources=[DOC_URI], server_name="demo__two")


@pytest.mark.asyncio
async def test_credential_bearing_provider_metadata_is_refused_like_a_credential_uri(db) -> None:
    workspace = await create_mcp_workspace(db)

    result = await mirror_catalog(
        db,
        workspace,
        resources=[
            mcp_resource(DOC_URI, description=f"Mirrored from {POSTGRES_URI}"),
            mcp_resource(OTHER_URI, name=f"report {PRESIGNED_URI}"),
            mcp_resource("docs://svelte", mime_type=f"text/plain;src={PRESIGNED_URI}"),
            mcp_resource("docs://ember"),
        ],
        prompts=[
            mcp_prompt(PROMPT, description=f"See {POSTGRES_URI}"),
            mcp_prompt(
                OTHER_PROMPT,
                arguments=[{"name": "topic", "description": f"Fetch from {POSTGRES_URI}", "required": True}],
            ),
            mcp_prompt("safe-prompt"),
        ],
    )

    assert result["resources"]["mirrored"] == 1
    assert result["prompts"]["mirrored"] == 1
    assert result["resources"]["rejected_entries"] == [
        "[description:uri_userinfo]",
        "[mimeType:uri_credential_query_parameter]",
        "[name:uri_credential_query_parameter]",
    ]
    assert result["prompts"]["rejected_entries"] == [
        "[argumentDescription:uri_userinfo]",
        "[description:uri_userinfo]",
    ]
    assert "s3cr3t-token" not in str(result)
    with pytest.raises(NoResultFound):
        await resource_binding(db, workspace, DOC_URI)
    with pytest.raises(NoResultFound):
        await prompt_binding(db, workspace, PROMPT)


@pytest.mark.asyncio
async def test_hostile_prompt_names_are_refused_by_code_and_never_echoed(db) -> None:
    workspace = await create_mcp_workspace(db)
    oversized = "p" * 500
    ambiguous = "summarize__docs::" + "x" * 40
    credential_named = f"prompt-{POSTGRES_URI}"

    result = await mirror_catalog(
        db,
        workspace,
        prompts=[mcp_prompt(oversized), mcp_prompt(ambiguous), mcp_prompt(credential_named), PROMPT],
    )

    assert result["prompts"]["mirrored"] == 1
    assert result["prompts"]["rejected_entries"] == sorted(
        ["[prompt_identifier_too_long]", "[ambiguous_prompt_name]", "[name:uri_userinfo]"]
    )
    payload = str(result)
    assert oversized not in payload
    assert "xxxx" not in payload
    assert "s3cr3t-token" not in payload
    assert max(len(entry) for entry in result["prompts"]["rejected_entries"]) <= 60
    await prompt_binding(db, workspace, PROMPT)
