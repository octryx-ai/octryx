"""Secret-shaped values in mirrored metadata never persist, while harmless status fields and ordinary wording still mirror."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import CapabilityType, WorkspaceCapabilityBinding
from app.services.mcp_resource_contract import mcp_resource_contract_credential_finding
from app.services.mcp_resource_identity import MCP_RESOURCE_KIND
from app.services.mcp_resource_index import load_mcp_resource_index
from app.services.mcp_resource_policy import decide_mcp_resource
from app.services.mcp_resource_states import STATE_CREDENTIAL_METADATA
from app.tools.registry import execute_tool_with_plugins
from tests.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.mcp_resource_support import (
    DOC_URI,
    LIST_RESOURCES_TOOL,
    POSTGRES_URI,
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


@pytest.mark.asyncio
async def test_short_and_word_shaped_secret_assignments_never_persist(db) -> None:
    """Explicit secret fields fail closed even when a generic redactor misses them."""
    workspace = await create_mcp_workspace(db)
    raw_values = (
        "correcthorse",
        "deadbeef",
        "shortSecret9",
        "Abcd1234",
        "8f3a9c21",
    )

    result = await mirror_catalog(
        db,
        workspace,
        resources=[
            mcp_resource("docs://passwd", description=f"passwd: {raw_values[0]}"),
            mcp_resource("docs://hex", description=f"access-key: {raw_values[1]}"),
            mcp_resource("docs://aws", description=f"aws_secret_access_key: {raw_values[2]}"),
        ],
        prompts=[
            mcp_prompt("auth-secret", description=f"Authorization: {raw_values[3]}"),
            mcp_prompt(
                "argument-secret",
                arguments=[{"name": "topic", "description": f"token: {raw_values[4]}", "required": True}],
            ),
        ],
    )

    assert result["resources"]["mirrored"] == 0
    assert result["prompts"]["mirrored"] == 0
    assert result["resources"]["rejected_entries"] == ["[description:uri_secret_value]"] * 3
    assert result["prompts"]["rejected_entries"] == [
        "[argumentDescription:uri_secret_value]",
        "[description:uri_secret_value]",
    ]
    capability_types = (await db.execute(select(CapabilityType))).scalars().all()
    bindings = (await db.execute(select(WorkspaceCapabilityBinding))).scalars().all()
    persisted = json.dumps(
        [
            {"name": row.name, "description": row.description, "contract": row.contract}
            for row in capability_types
        ]
        + [
            {
                "display_name": row.display_name,
                "binding_config": row.binding_config,
                "policy_config": row.policy_config,
            }
            for row in bindings
        ],
        sort_keys=True,
        default=str,
    )
    for raw_value in raw_values:
        assert raw_value not in str(result)
        assert raw_value not in persisted


@pytest.mark.asyncio
async def test_harmless_secret_status_fields_still_mirror(db) -> None:
    """Closed documentation statuses remain ordinary business metadata."""
    workspace = await create_mcp_workspace(db)

    result = await mirror_catalog(
        db,
        workspace,
        resources=[
            mcp_resource("docs://required", description="Password: Required for download"),
            mcp_resource("docs://approved", description="Authorization: Approved by the board"),
        ],
        prompts=[
            mcp_prompt("unlimited", description="Token: unlimited"),
            mcp_prompt(
                "undisclosed",
                arguments=[{"name": "topic", "description": "secret: undisclosed", "required": True}],
            ),
        ],
    )

    assert result["resources"]["mirrored"] == 2
    assert result["resources"]["rejected_entries"] == []
    assert result["prompts"]["mirrored"] == 2
    assert result["prompts"]["rejected_entries"] == []
    bindings = [
        await resource_binding(db, workspace, "docs://required"),
        await resource_binding(db, workspace, "docs://approved"),
        await prompt_binding(db, workspace, "unlimited"),
        await prompt_binding(db, workspace, "undisclosed"),
    ]
    for binding in bindings:
        assert mcp_resource_contract_credential_finding(binding.capability_type.contract) == ""


@pytest.mark.asyncio
async def test_a_row_whose_stored_metadata_holds_a_credential_fails_closed(db, monkeypatch) -> None:
    """A mirrored record whose stored metadata holds a credential is withheld, not published."""
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    binding = await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT))
    binding.capability_type.contract = {
        **binding.capability_type.contract,
        "description": f"Mirrored from {POSTGRES_URI}",
    }
    await db.flush()
    context = resource_context(workspace, db)

    read = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)
    listing = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)
    index = await load_mcp_resource_index(db, workspace_id=workspace.project.id)
    decision = decide_mcp_resource(
        index, kind=MCP_RESOURCE_KIND, server_name=SERVER, identity=resource_id(DOC_URI)
    )

    assert decision.state == STATE_CREDENTIAL_METADATA
    assert decision.governed_identity == ""
    assert read["reason"] == "mcp_resource_not_available"
    # Neither the credential nor the entry survives into a model-visible payload.
    assert listing["resources"] == []
    assert "s3cr3t-token" not in str(read) + str(listing)
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_ordinary_risk_and_task_wording_is_mirrored_rather_than_refused(db) -> None:
    """A governed catalog has to be usable by the business that owns it.

    "risk-report", "task-summary", "desk-review" and "Basic ..." are what a real
    server names its resources and prompts, and each of them contains a substring
    the shared secret heuristic reads as key material. Refusing them would leave a
    workspace unable to mirror its own catalog — and would mark an approved
    binding as refused on the next run.
    """
    workspace = await create_mcp_workspace(db)

    result = await mirror_catalog(
        db,
        workspace,
        resources=[
            mcp_resource(
                "docs://risk-report",
                name="risk-report",
                description="Quarterly risk-report for the desk-review board, basic figures only.",
            ),
            mcp_resource(
                "docs://task-summary",
                name="task-summary",
                description="Basic reporting guidance: one task-summary per desk.",
                mime_type="application/vnd.octryx.risk-report+json",
            ),
        ],
        prompts=[
            mcp_prompt("risk-report-basics", description="Basic desk-review task-summary for the risk board"),
            mcp_prompt(
                "task-summary-desk",
                arguments=[{"name": "desk", "description": "Basic desk-review scope", "required": True}],
            ),
        ],
    )

    assert result["resources"] == {**result["resources"], "mirrored": 2, "added": 2, "rejected_entries": []}
    assert result["prompts"] == {**result["prompts"], "mirrored": 2, "added": 2, "rejected_entries": []}
    await resource_binding(db, workspace, "docs://risk-report")
    await prompt_binding(db, workspace, "risk-report-basics")
