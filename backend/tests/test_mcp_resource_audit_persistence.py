"""Persisted governance rows never carry a resource URI, fit their column, and a failed audit insert keeps the transaction usable."""

from __future__ import annotations

import pytest

from app.models import AuditLog
from app.services.mcp_resource_audit import (
    GOVERNANCE_AUDIT_KEY,
    GOVERNANCE_AUDIT_UNAVAILABLE,
    OUTCOME_AWAITING_APPROVAL,
    OUTCOME_DENIED,
    OUTCOME_EXECUTED,
)
from app.services.mcp_resource_identity import (
    MAX_AUDIT_RESOURCE_ID_CHARS,
    MCP_PROMPT_KIND,
    MCP_RESOURCE_KIND,
    audit_resource_reference,
)
from app.tools.registry import execute_tool_with_plugins
from tests.mcp_resource_audit_support import _audit_rows
from tests.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.mcp_resource_support import (
    DOC_URI,
    GET_PROMPT_TOOL,
    LIST_RESOURCES_TOOL,
    OTHER_URI,
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
async def test_no_persisted_governance_row_carries_a_resource_uri_in_any_form(db, monkeypatch) -> None:
    """Sweep every row this surface can write, for both kinds and all outcomes.

    A governed URI is redacted, not harmless: it still names an internal host, a
    bucket, or a database. The catalog is where an operator resolves an identity
    to a URI; an audit row only says which catalog entry was decided.
    """
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI, OTHER_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT), risk="write")
    context = resource_context(workspace, db, approval_policy={"require_for_risks": ["write"]})

    await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)
    await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)
    await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(OTHER_URI), context)
    await execute_tool_with_plugins(
        GET_PROMPT_TOOL, {"server_name": SERVER, "prompt_name": PROMPT, "arguments": {"topic": "hunter2"}}, context
    )

    rows = await _audit_rows(db, workspace)
    evidence = str([row.details for row in rows])
    assert {row.details["outcome"] for row in rows} == {
        OUTCOME_EXECUTED,
        OUTCOME_DENIED,
        OUTCOME_AWAITING_APPROVAL,
    }
    assert "docs://" not in evidence
    assert DOC_URI not in evidence and OTHER_URI not in evidence
    assert "hunter2" not in evidence
    # The opaque identity is what every row uses instead.
    assert resource_id(DOC_URI) in evidence


def test_the_audit_reference_always_fits_the_persisted_column() -> None:
    """``AuditLog.resource_id`` is ``String(200)`` and PostgreSQL enforces it.

    SQLite does not, so the width contract is asserted against the column itself
    rather than against whichever database a test run happens to use. An
    over-width value on PostgreSQL fails the insert, aborts the transaction the
    caller is still using, and takes the governance outcome with it — so no
    model- or provider-supplied identity may reach that column unbounded.
    """
    width = AuditLog.__table__.c.resource_id.type.length
    assert width == MAX_AUDIT_RESOURCE_ID_CHARS

    hostile = "p" * 5000
    for kind in (MCP_RESOURCE_KIND, MCP_PROMPT_KIND):
        reference = audit_resource_reference(
            kind=kind, server_name="s" * 400, binding_key="", identity=hostile
        )
        assert 0 < len(reference) <= width
        assert hostile[:50] not in reference
        # Stable: two audits of the same unknown item line up.
        assert reference == audit_resource_reference(
            kind=kind, server_name="s" * 400, binding_key="", identity=hostile
        )
        # And two different unknown items do not collapse onto one reference.
        assert reference != audit_resource_reference(
            kind=kind, server_name="s" * 400, binding_key="", identity=hostile + "q"
        )
    # A binding key the catalog could not have written is not passed through either.
    assert len(
        audit_resource_reference(kind=MCP_PROMPT_KIND, server_name=SERVER, binding_key="k" * 400, identity="x")
    ) <= width
    # A mirrored item is still named by its catalog key.
    assert audit_resource_reference(
        kind=MCP_RESOURCE_KIND, server_name=SERVER, binding_key="mcp-resource:demo:abc", identity="abc"
    ) == "mcp-resource:demo:abc"


@pytest.mark.asyncio
async def test_an_oversized_prompt_name_denies_and_is_audited_within_the_column(db, monkeypatch) -> None:
    """The hostile end-to-end version of the width contract."""
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, prompts=[PROMPT])
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT))
    hostile = "p" * 5000

    result = await execute_tool_with_plugins(
        GET_PROMPT_TOOL,
        {"server_name": SERVER, "prompt_name": hostile, "arguments": {}},
        resource_context(workspace, db),
    )

    assert result["reason"] == "mcp_prompt_not_available"
    assert manager.touched_remote is False
    rows = await _audit_rows(db, workspace)
    assert len(rows) == 1
    assert len(rows[0].resource_id) <= AuditLog.__table__.c.resource_id.type.length
    assert hostile[:50] not in str(rows[0].resource_id) + str(rows[0].details)


@pytest.mark.asyncio
async def test_a_failed_audit_insert_leaves_the_transaction_usable_and_says_so(db, monkeypatch) -> None:
    """An audit failure must cost the row, not the turn.

    The writer runs inside the caller's transaction. Before the SAVEPOINT the
    failed insert aborted that transaction, so a swallowed audit error took the
    turn's own writes with it — and nothing on the result said the governance
    outcome had no evidence. Both halves are pinned here by forcing every
    governance insert onto one primary key.
    """
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    context = resource_context(workspace, db)

    def _colliding_audit_log(**fields):
        return AuditLog(id="one-governance-row", **fields)

    monkeypatch.setattr("app.services.mcp_resource_audit.AuditLog", _colliding_audit_log)
    first = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)
    second = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)

    assert first["success"] is True
    assert GOVERNANCE_AUDIT_KEY not in first
    # The read still happened; what is gone is its evidence, and it says so.
    assert second["success"] is True
    assert second[GOVERNANCE_AUDIT_KEY] == GOVERNANCE_AUDIT_UNAVAILABLE
    # The caller's transaction survived the failed insert: it can still read and
    # still write. Before the SAVEPOINT this raised ``PendingRollbackError``.
    rows = await _audit_rows(db, workspace)
    assert len(rows) == 1
    assert rows[0].details["outcome"] == OUTCOME_EXECUTED
    monkeypatch.undo()
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk="admin")
    assert (await resource_binding(db, workspace, DOC_URI)).policy_config["risk"] == "admin"
