"""The chat follows and steers its own runs and uses the client's knowledge extras, writing only after the person confirms."""

from __future__ import annotations

import pytest

from app.services.governed_default_tool_sets import governed_default_tool_set
from app.tools.context import ToolContext
from tests.chat_session_tools_support import CHAT_STATE, _confirmed_again
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_a_chat_follows_its_run_and_decides_it_only_after_the_person_confirms(db):
    from sqlalchemy import select

    from app.models import WorkflowRunDecision
    from app.services.workflow_runs.records import new_chat_session, start_run
    from app.tools.registry import execute_tool
    from tests.knowledge_evidence_seed_support import seed_workspace
    from tests.phased_workflow_fixtures import member_admin, publish_phased
    from tests.test_workflow_run_octryx_decisions import CONFIRM, _definition

    workspace_id = await seed_workspace(db)
    admin = await member_admin(db, workspace_id)
    chat = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition(CONFIRM)),
                          project_id=workspace_id, session=chat)
    context = ToolContext(user_id=admin.id, project_ids=[workspace_id], roles=["admin"], session_id=chat.id,
                          project_config={}, db=db, agent_mode_key="diagnosis", capability_type="diagnosis",
                          run_capability=dict(CHAT_STATE))

    catalog = await execute_tool("workflow_catalog", {}, context)
    assert catalog["state"] == "ok" and catalog["workspace_id"] == workspace_id
    status = await execute_tool("workflow_run_status", {}, context)
    decision = status["workflow_run"]["decision"]
    assert status["state"] == "ok" and decision["in_terminal"] is True

    decide = {"run_id": run.id, "action": "confirm", "payload_hash": decision["payload_hash"]}
    held = await execute_tool("workflow_decide", decide, context)
    assert held["code"] == "write_plan_required" and run.status == "waiting"
    decided = await _confirmed_again(db, admin.id, held, "workflow_decide", decide, context)
    assert decided["state"] == "decided" and decided["workflow_run"]["phase"]["node_id"] == "work"
    [row] = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id))).scalars()
    assert (row.action, row.decided_by) == ("confirmed", admin.id)


@pytest.mark.asyncio
async def test_a_chat_continues_only_its_own_run_and_an_mcp_http_caller_still_needs_the_prompt(db):
    from app.services.mcp_governed_knowledge import McpCaller
    from app.services.mcp_workflow_run_tools import mcp_workflow_decide
    from app.services.workflow_runs.records import active_run_for_session, new_chat_session, start_run
    from app.tools.registry import execute_tool
    from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
    from tests.phased_workflow_fixtures import admin_user, publish_phased
    from tests.test_workflow_run_octryx_decisions import CONFIRM, _definition

    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition(CONFIRM)),
                          project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    other_chat = await new_chat_session(db, admin, workspace_id)
    context = ToolContext(user_id=admin.id, project_ids=[workspace_id], roles=["admin"], session_id=other_chat.id,
                          project_config={}, db=db, agent_mode_key="diagnosis", capability_type="diagnosis",
                          run_capability=dict(CHAT_STATE))
    assert (await execute_tool("workflow_run_status", {}, context))["reason"] == "no_run_bound"
    held = await execute_tool("workflow_select", {"run_id": run.id}, context)
    followed = await _confirmed_again(db, admin.id, held, "workflow_select", {"run_id": run.id}, context)
    assert followed["state"] == "selected" and (await active_run_for_session(db, other_chat.id)).id == run.id

    member = await seed_member(db, workspace_id=workspace_id, role="member", username="chatparity-member")
    their_chat = await new_chat_session(db, await db.get(type(admin), member), workspace_id)
    theirs = ToolContext(user_id=member, project_ids=[workspace_id], roles=["member"], session_id=their_chat.id,
                         project_config={}, db=db, agent_mode_key="diagnosis", capability_type="diagnosis",
                         run_capability=dict(CHAT_STATE))
    held = await execute_tool("workflow_select", {"run_id": run.id}, theirs)
    refused = await _confirmed_again(db, member, held, "workflow_select", {"run_id": run.id}, theirs)
    assert refused["state"] in {"denied", "not_found"}

    # The chat transport is no back door for the client: an HTTP caller still needs the permission prompt.
    http = McpCaller(user_id=admin.id, grant_id="g", scopes=("workflow:execute",), workspace_header=workspace_id,
                     transport="http", chat_session_id=other_chat.id)
    answer = await mcp_workflow_decide(db, caller=http, user=admin, workspace_id=workspace_id,
                                       arguments={"run_id": run.id, "action": "confirm", "payload_hash": "x"})
    assert answer["reason"] == "mcp_channel_required"


def test_the_chat_set_offers_the_clients_run_steering():
    from app.tools.capability_requirements import tool_required_capability
    from app.tools.definitions import get_tool_definition_metadata

    tools = set(governed_default_tool_set("diagnosis").tools)
    writes = {"workflow_select", "workflow_decide", "workflow_action_request"}
    reads = {"workflow_catalog", "workflow_run_status", "approval_get", "approval_list",
             "product_run_list", "task_list", "task_runs", "policy_effective"}
    assert reads | writes <= tools
    assert {name for name in reads | writes if get_tool_definition_metadata(name).risk == "write"} == writes
    assert {tool_required_capability(name) for name in writes} == {"read_only"}


@pytest.mark.asyncio
async def test_a_chat_reads_the_clients_knowledge_extras_freely_and_rates_an_answer_after_confirming(db):
    import uuid

    from app.models import Message, User
    from app.services.workflow_runs.records import new_chat_session
    from app.tools.registry import execute_tool
    from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

    workspace_id = await seed_workspace(db)
    admin = await db.get(User, await seed_member(db, workspace_id=workspace_id, role="member",
                                                 username=f"extras{uuid.uuid4().hex[:6]}"))
    chat = await new_chat_session(db, admin, workspace_id)
    answer = Message(id=str(uuid.uuid4()), session_id=chat.id, role="assistant", content="Java 21.")
    db.add(answer)
    await db.flush()
    context = ToolContext(user_id=admin.id, project_ids=[workspace_id], roles=["member"], session_id=chat.id,
                          project_config={}, db=db, agent_mode_key="diagnosis", capability_type="diagnosis",
                          run_capability=dict(CHAT_STATE))

    projects = await execute_tool("knowledge_projects", {}, context)
    assert [project["id"] for project in projects["projects"]] == [workspace_id], "bound to the chat's Workspace"
    assert (await execute_tool("knowledge_sources", {}, context))["workspace_id"] == workspace_id
    found = await execute_tool("entity_search", {"query": "payments"}, context)
    assert "items" in found and "approval_required" not in found

    rate = {"session_id": chat.id, "message_id": answer.id, "rating": "good"}
    held = await execute_tool("knowledge_feedback", rate, context)
    rated = await _confirmed_again(db, admin.id, held, "knowledge_feedback", rate, context)
    assert rated["state"] == "recorded" and rated["rating"] == "good"


def test_the_chat_set_offers_the_clients_knowledge_extras():
    from app.tools.definitions import get_tool_definition_metadata

    extras = {"knowledge_sources", "knowledge_projects", "entity_search", "entity_neighbors", "knowledge_feedback"}
    assert extras <= set(governed_default_tool_set("diagnosis").tools)
    assert {name for name in extras if get_tool_definition_metadata(name).risk == "write"} == {"knowledge_feedback"}
