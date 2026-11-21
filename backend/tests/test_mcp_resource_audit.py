"""Audit evidence for governed MCP resource and prompt access.

The model-visible denial is deliberately uniform, so the audit record is the only
place the precise governance state survives. These tests pin three halves of that
contract: the record carries the exact internal state, it carries the *final*
outcome rather than the pre-approval policy answer, and it carries nothing that
could leak a credential, a raw URI, or an argument payload.
"""

from __future__ import annotations

import pytest

from app.services.mcp_resource_audit import (
    DISPATCH_OUT_OF_BAND,
    DISPATCH_TOOL,
    OUTCOME_AWAITING_APPROVAL,
    OUTCOME_DENIED,
    OUTCOME_EXECUTED,
)
from app.services.mcp_resource_identity import MCP_PROMPT_KIND, MCP_RESOURCE_KIND
from app.services.mcp_resource_states import (
    MCP_RESOURCE_DECISION_STATES,
    STATE_ALLOWED,
    STATE_CREDENTIAL_URI,
    STATE_DISABLED,
    STATE_NOT_MIRRORED,
)
from app.tools.mcp_resource_bridge import ReadMcpServerResourceTool
from app.tools.registry import execute_tool_with_plugins
from tests.mcp_resource_audit_support import _audit_rows
from tests.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.mcp_resource_support import (
    DOC_URI,
    GET_PROMPT_TOOL,
    OTHER_URI,
    POSTGRES_URI,
    PROMPT,
    READ_RESOURCE_TOOL,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mirror_catalog,
    prompt_binding,
    read_params,
    resource_binding,
    resource_context,
    resource_id,
)


@pytest.mark.asyncio
async def test_an_allowed_read_records_one_redaction_safe_row(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    binding = await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk="read")

    await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))

    rows = await _audit_rows(db, workspace)
    # One governed request, one row: the pre-transport check consumes what
    # registry dispatch already enforced instead of auditing it again.
    assert len(rows) == 1
    row = rows[0]
    assert row.resource_type == MCP_RESOURCE_KIND
    assert row.resource_id == binding.binding_key
    assert row.user_id == workspace.user.id
    assert row.session_id == workspace.session.id
    assert row.details["state"] == STATE_ALLOWED
    assert row.details["allowed"] is True
    assert row.details["outcome"] == OUTCOME_EXECUTED
    assert row.details["risk"] == "read"
    assert row.details["dispatch"] == DISPATCH_TOOL
    assert row.details["tool_name"] == READ_RESOURCE_TOOL
    assert row.details["identity"] == resource_id(DOC_URI)
    # The opaque catalog identity is the *only* way the row names the item. The
    # governed URI is not a substitute for it: even redacted it still names an
    # internal host, a bucket, or a database, so it is not in the row at all.
    assert DOC_URI not in str(row.details)
    assert "docs://" not in str(row.details)
    assert set(row.details) == {
        "kind",
        "server_name",
        "identity",
        "binding_key",
        "allowed",
        "state",
        "public_reason",
        "risk",
        "scopes",
        "matched_rule",
        "workspace_id",
        "dispatch",
        "tool_name",
        "outcome",
    }


@pytest.mark.asyncio
async def test_a_denial_records_the_precise_state_the_model_never_sees(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    context = resource_context(workspace, db)

    disabled = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(DOC_URI), context)
    unknown = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(OTHER_URI), context)

    assert disabled["reason"] == unknown["reason"] == "mcp_resource_not_available"
    rows = await _audit_rows(db, workspace)
    assert [row.details["state"] for row in rows] == [STATE_DISABLED, STATE_NOT_MIRRORED]
    assert {row.details["outcome"] for row in rows} == {OUTCOME_DENIED}
    # The audited state always comes from the closed vocabulary, never free text.
    assert {row.details["state"] for row in rows} <= set(MCP_RESOURCE_DECISION_STATES)


@pytest.mark.asyncio
async def test_a_credential_bearing_uri_never_reaches_the_audit_record(db, monkeypatch) -> None:
    """The refused URI is neither mirrored nor audited; only its digest is."""
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[POSTGRES_URI])

    await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(POSTGRES_URI), resource_context(workspace, db))

    rows = await _audit_rows(db, workspace)
    assert len(rows) == 1
    assert "s3cr3t-token" not in str(rows[0].details)
    assert "db.internal" not in str(rows[0].details)
    assert rows[0].details["state"] == STATE_NOT_MIRRORED
    assert rows[0].details["identity"] == resource_id(POSTGRES_URI)


@pytest.mark.asyncio
async def test_a_binding_that_still_holds_a_credential_uri_is_audited_as_such(db, monkeypatch) -> None:
    """A stored binding that holds a credential URI fails closed, and the audit record says why."""
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    binding = await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    binding.binding_config = {**binding.binding_config, "resourceUri": POSTGRES_URI}
    await db.flush()

    result = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))

    rows = await _audit_rows(db, workspace)
    assert result["reason"] == "mcp_resource_not_available"
    assert rows[-1].details["state"] == STATE_CREDENTIAL_URI
    assert "s3cr3t-token" not in str(rows[-1].details)


@pytest.mark.asyncio
async def test_a_held_approval_is_never_audited_as_an_executed_allow(db, monkeypatch) -> None:
    """Policy said yes, the approval gate said wait: that is not an execution."""
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, prompts=[PROMPT])
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT), risk="write")

    await execute_tool_with_plugins(
        GET_PROMPT_TOOL,
        {"server_name": SERVER, "prompt_name": PROMPT, "arguments": {"topic": "hunter2"}},
        resource_context(workspace, db, approval_policy={"require_for_risks": ["write"]}),
    )

    rows = await _audit_rows(db, workspace)
    assert [row.resource_type for row in rows] == [MCP_PROMPT_KIND]
    assert rows[0].details["state"] == STATE_ALLOWED
    assert rows[0].details["outcome"] == OUTCOME_AWAITING_APPROVAL
    assert "hunter2" not in str(rows[0].details)


@pytest.mark.asyncio
async def test_a_direct_execution_records_its_own_final_outcome(db, monkeypatch) -> None:
    """Outside registry dispatch there is no mark to consume, so the tool audits."""
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))

    allowed = await ReadMcpServerResourceTool().execute(read_params(), resource_context(workspace, db))
    denied = await ReadMcpServerResourceTool().execute(read_params(OTHER_URI), resource_context(workspace, db))

    rows = await _audit_rows(db, workspace)
    assert allowed["contents"][0]["text"] == "# React"
    assert denied["reason"] == "mcp_resource_not_available"
    assert [row.details["dispatch"] for row in rows] == [DISPATCH_OUT_OF_BAND, DISPATCH_OUT_OF_BAND]
    assert [row.details["outcome"] for row in rows] == [OUTCOME_EXECUTED, OUTCOME_DENIED]
