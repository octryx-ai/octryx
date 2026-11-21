"""Claude Code parity over MCP: contract tests over the native OAuth path.

- the MCP surface has no mode parameter and offers code impact, the workflow tools, resources and
  prompts, approvals and Product Run status;
- the Workspace is the connection's: a foreign Workspace is ``not_found``, and the project tool
  policy holds over MCP;
- ``knowledge_code_impact`` answers from explicit client files, or from the session's bound
  repository snapshot, with cited facts (``cite_as``) and one link per location. The link is the
  host's ``blob/<sha>/<path>#L<n>`` for a clean, pushed tree, and the platform viewer otherwise;
- a change-class workflow answers ``needs_confirmation`` with a governed approval. Only a gateway
  confirmation ticket (the user accepted Claude Code's permission prompt) approves it over MCP;
- the shared MCP rate limit (per grant and tool) holds for the new tools.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.models import Approval
from app.services import mcp_knowledge_observability
from app.services.agent_gateway.confirmation import ask_for_confirmation
from app.services.mcp_extra_tools import EXTRA_GOVERNED_MCP_TOOLS, EXTRA_HANDLER_MCP_TOOLS
from app.services.mcp_parity_dispatch import run_parity_mcp_tool
from tests.agent_gateway_hook_support import confirm_hook_input, new_hook_key, register
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.mcp_claude_code_parity_support import SCOPES, _caller, _gateway_session, _native
from tests.mcp_native_support import mcp_request, native_token
from tests.phased_workflow_fixtures import phased_definition, publish_phased


async def test_the_mcp_surface_has_no_modes_and_offers_the_parity_capabilities(db, monkeypatch):
    _native(db, monkeypatch)
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    token = await native_token(db, user_id=member_id, scopes=list(SCOPES))

    tools = (await mcp_request(token, "tools/list"))["result"]["tools"]
    names = {tool["name"] for tool in tools}
    parity = {"knowledge_code_impact", "workflow_catalog", "workflow_select", "workflow_confirm", "approval_get",
              "product_run_list", *EXTRA_GOVERNED_MCP_TOOLS, *EXTRA_HANDLER_MCP_TOOLS}
    assert parity <= names
    for tool in tools:
        properties = set(tool["inputSchema"].get("properties") or {})
        assert not {"mode", "agent_type", "agent_mode"} & properties, tool["name"]
        if tool["name"] in parity:
            assert not {"project_id", "workspace_id", "user_id"} & properties, tool["name"]
    templates = (await mcp_request(token, "resources/templates/list"))["result"]["resourceTemplates"]
    assert "octryx://workflow-catalog" in {item["uriTemplate"] for item in templates}


async def test_a_run_start_confirmation_through_the_permission_prompt(db, monkeypatch):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    from app.models.runtime.secure_work import WorkItem

    workflow_key = await publish_phased(db, phased_definition())
    db.add(WorkItem(source_type="jira", source_instance="t", source_key="PAY-61", title="x", project_id=workspace_id))
    await db.flush()
    session_key = str(uuid.uuid4())
    gateway = await _gateway_session(db, member_id, workspace_id, session_key)
    await db.commit()
    caller = _caller(member_id, workspace_id, session_key=session_key)

    async def call(tool, **arguments):
        result = await run_parity_mcp_tool(db, caller=caller, tool_name=tool, arguments=arguments)
        await db.commit()
        return result

    catalog = {entry["workflow_key"]: entry for entry in (await call("workflow_catalog"))["workflows"]}
    assert workflow_key in catalog
    assert (await call("workflow_select", workflow_key="nope"))["state"] == "needs_clarification"

    # Starting a phased run for a Work item waits for the user's confirmation.
    change = await call("workflow_select", workflow_key=workflow_key, work_item="PAY-61")
    assert change["state"] == "needs_confirmation"
    approval_id = change["approval_id"]
    assert (await call("workflow_select", workflow_key=workflow_key, work_item="PAY-61"))["approval_id"] == approval_id
    assert (await call("approval_get", approval_id=approval_id))["approval"]["status"] == "pending"

    # Without the gateway's ask ticket (a plain MCP client), the confirmation stays in the platform UI.
    plain = await call("workflow_confirm", approval_id=approval_id)
    assert (plain["state"], plain["reason"]) == ("needs_confirmation", "confirm_in_platform")
    # The PreToolUse hook proved itself with the launcher's key, the platform asked, the user accepted
    # the prompt, and Claude Code's MCP call carries the ticket and its tool_use id: approved, once.
    key = new_hook_key()
    assert await register(db, gateway, key) is None
    hook_input = confirm_hook_input(key, session_key=session_key, approval_id=approval_id)
    asked = await ask_for_confirmation(db, session=gateway, session_key=session_key, hook_input=hook_input)
    await db.commit()
    assert (asked["decision"], asked["state"]) == ("ask", "needs_confirmation")
    caller = _caller(member_id, workspace_id, session_key=session_key, tool_use_id=hook_input["tool_use_id"])
    ticket = asked["confirmation_ticket"]
    confirmed = await call("workflow_confirm", approval_id=approval_id, confirmation_ticket=ticket)
    assert confirmed["state"] == "selected" and confirmed["approval_id"] == approval_id
    approval = await db.get(Approval, approval_id)
    assert (approval.status, approval.approved_by) == ("approved", member_id)

    # A teammate may read it (session read rule of a team Workspace) but never confirm it; a user of
    # another Workspace sees nothing, and naming this Workspace from outside is not_found.
    teammate = _caller(await seed_member(db, workspace_id=workspace_id, role="member"), workspace_id)
    other = await run_parity_mcp_tool(
        db, caller=teammate, tool_name="workflow_confirm", arguments={"approval_id": approval_id}
    )
    assert other["state"] == "not_found"
    elsewhere_id = await seed_workspace(db)
    outsider_id = await seed_member(db, workspace_id=elsewhere_id, role="member")
    for header in (elsewhere_id, workspace_id):
        outsider = _caller(outsider_id, header)
        seen = await run_parity_mcp_tool(
            db, caller=outsider, tool_name="approval_get", arguments={"approval_id": approval_id}
        )
        assert seen["state"] == "not_found"
    # Scope: without workflow:execute nothing is confirmed.
    narrow = _caller(member_id, workspace_id, scopes=("knowledge:read", "workflow:read"))
    refused = await run_parity_mcp_tool(db, caller=narrow, tool_name="workflow_confirm", arguments={"approval_id": "x"})
    assert refused["state"] == "denied"


async def test_parity_tools_share_the_mcp_rate_limit(db, monkeypatch):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    mcp_knowledge_observability.clear_mcp_knowledge_observability_state()
    monkeypatch.setattr(mcp_knowledge_observability, "MCP_KNOWLEDGE_RATE_LIMIT_MAX_REQUESTS", 2)
    caller = _caller(member_id, workspace_id)
    try:
        for _ in range(2):
            await run_parity_mcp_tool(db, caller=caller, tool_name="product_run_list", arguments={})
        with pytest.raises(HTTPException) as limited:
            await run_parity_mcp_tool(db, caller=caller, tool_name="product_run_list", arguments={})
        assert limited.value.status_code == 429
    finally:
        mcp_knowledge_observability.clear_mcp_knowledge_observability_state()
