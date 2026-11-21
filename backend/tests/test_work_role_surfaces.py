"""Role-based tools on both surfaces: the chat's offered tools and its
dispatch, the client's MCP tools/list and calls, the trusted role, delivery per connection, the product-owner gate,
``function:``/``role:`` deciders and per-role phase shell rules. All inert while the Workspace switch is off.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Session as AgentSession
from app.models import User
from app.models.runtime.work_role_model import WorkRole, WorkRoleAssignment, WorkspaceWorkRoleSettings
from app.services.work_role_model.commands import role_command_allowed, role_command_denial, with_role_commands
from app.services.work_role_model.effective import HeldRole, WorkRoleGrant, effective_permission
from app.services.work_role_model.seeds import ensure_seed_catalog
from app.services.work_role_model.surfaces import (
    filter_definitions,
    prompt_note,
    with_prompt_note,
    write_connection_refusal,
)
from app.services.workflow_runs.decider import po_function_refusal, validate_decider_config
from app.services.workflow_runs.work_roles import work_role_members
from app.tools.context import ToolContext
from tests.chat_connector_writes_support import CHAT_STATE, EPIC, JIRA, _offered
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

pytestmark = pytest.mark.asyncio


def _grant(*roles: HeldRole, enforced: bool = True) -> WorkRoleGrant:
    return WorkRoleGrant(workspace_id="ws", user_id="u1", enforced=enforced, roles=roles)


def _role(key="viewer", entries=("risk:read",), functions=("read",), trusted=False, delivery="all",
          connections=(), allow=(), deny=()) -> HeldRole:
    return HeldRole(id=key, key=key, name=key.title(), trusted=trusted, delivery_connections=delivery,
                    connection_ids=tuple(connections), command_allow=tuple(allow), command_deny=tuple(deny),
                    functions=tuple(functions), entries=tuple(entries))


async def _seeded(db):
    await ensure_seed_catalog(db)
    workspace = await seed_workspace(db)
    member = await seed_member(db, workspace_id=workspace, role="member")
    await db.flush()
    return workspace, member


async def _assign(db, workspace, user_id, key, *, switch=True):
    role = (await db.execute(select(WorkRole).where(WorkRole.key == key, WorkRole.project_id.is_(None)))
            ).scalar_one()
    db.add(WorkRoleAssignment(project_id=workspace, role_id=role.id, subject_kind="user", user_id=user_id,
                              subject_key=user_id))
    if switch and await db.get(WorkspaceWorkRoleSettings, workspace) is None:
        db.add(WorkspaceWorkRoleSettings(project_id=workspace, role_based_tools=True))
    await db.flush()


# --- chat ---------------------------------------------------------------------------------------------------------

async def test_a_viewer_chat_offers_reads_only_and_no_role_offers_nothing(monkeypatch):
    everything = await _offered(CHAT_STATE)
    assert {"create_jira_ticket", "get_jira_ticket"} <= everything
    definitions = [{"function": {"name": name}} for name in sorted(everything)]
    viewer = {item["function"]["name"] for item in filter_definitions(definitions, _grant(_role()))}
    assert "get_jira_ticket" in viewer and "tool_search" in viewer
    assert "create_jira_ticket" not in viewer and "work_item_create" not in viewer
    assert filter_definitions(definitions, _grant()) == []
    assert filter_definitions(definitions, None) == definitions


async def test_the_chat_names_why_it_has_no_tools_and_a_trusted_role_is_announced():
    messages = [{"role": "system", "content": "base"}, {"role": "user", "content": "create the epic"}]
    noted = with_prompt_note(messages, prompt_note(_grant()))
    assert "no role in this Workspace" in noted[0]["content"]
    assert noted[1] == messages[1] and messages[0]["content"] == "base"
    assert "trusted" in prompt_note(_grant(_role(trusted=True)))
    assert prompt_note(None) is None and prompt_note(_grant(_role())) is None


@pytest.fixture
async def chat(db, monkeypatch):
    user = (await db.execute(select(User))).scalars().first()
    session = AgentSession(id="work-role-chat", user_id=user.id, agent_type="chat", status="active")
    db.add(session)
    await db.flush()
    calls: list[dict] = []
    from app.tools.registry import TOOL_REGISTRY

    async def execute(params, context):
        from app.tools.jira_impl._jira_helpers_ticket import _maybe_block_change_with_approval

        # The real Jira tool's own diagnosis-mode approval round trip, then a recorded write instead of HTTP.
        blocked = await _maybe_block_change_with_approval("create_jira_ticket", params, context,
                                                          action_title="Create Jira ticket in CHEF")
        if blocked is not None:
            return blocked
        calls.append(dict(params))
        return {"key": "CHEF-1"}

    monkeypatch.setattr(TOOL_REGISTRY["create_jira_ticket"], "execute", execute)

    def context(grant):
        return ToolContext(user_id=user.id, project_ids=[], roles=["member"], session_id=session.id,
                           project_config=dict(JIRA), db=db, agent_mode_key="diagnosis",
                           capability_type="diagnosis", run_capability=dict(CHAT_STATE), work_role_grant=grant)
    return context, calls


async def test_a_chat_call_outside_the_roles_is_refused_by_name_and_does_not_run(chat):
    from app.tools.registry import execute_tool

    context, calls = chat
    refused = await execute_tool("create_jira_ticket", EPIC, context(_grant(_role())))
    assert refused["code"] == "role_tool_not_granted" and "Viewer" in refused["error"] and calls == []
    nothing = await execute_tool("create_jira_ticket", EPIC, context(_grant()))
    assert nothing["code"] == "work_role_none" and "Workspace admin" in nothing["error"] and calls == []


async def test_a_trusted_role_writes_without_the_per_call_card_and_an_untrusted_one_is_asked(chat):
    from app.tools.registry import execute_tool

    context, calls = chat
    developer = _role("engineer", entries=("risk:read", "connector:*:write"), functions=("read", "delivery"))
    held = await execute_tool("create_jira_ticket", EPIC, context(_grant(developer)))
    # The chat write plan: an untrusted role's write does not run; it is asked once per request
    # through a plan, so the answer names the next step instead of a per-call card.
    assert held["code"] == "write_plan_required" and held["next_tool"] == "propose_write_plan"
    assert held["plan_write"] == {"tool": "create_jira_ticket", "fields": EPIC} and calls == []
    trusted = _role("engineer", entries=("risk:read", "connector:*:write"), functions=("read", "delivery"),
                    trusted=True)
    done = await execute_tool("create_jira_ticket", EPIC, context(_grant(trusted)))
    assert done.get("key") == "CHEF-1" and calls == [EPIC]


def test_delivery_is_granted_per_connection():
    selected = _grant(_role("doc_owner", entries=("connector:*:write",), delivery="selected",
                            connections=("conn-mm",)))
    context = SimpleNamespace(work_role_grant=selected)
    assert write_connection_refusal("create_jira_ticket", context, "conn-mm") is None
    refused = write_connection_refusal("create_jira_ticket", context, "conn-std", "Jira (Standard)")
    assert refused["code"] == "role_connection_not_granted" and "Jira (Standard)" in refused["error"]
    assert write_connection_refusal("get_jira_ticket", context, "conn-std") is None, "reads are not delivery"
    everyone = SimpleNamespace(work_role_grant=_grant(_role("engineer", entries=("connector:*:write",))))
    assert write_connection_refusal("create_jira_ticket", everyone, "conn-std") is None


# --- client (MCP) -------------------------------------------------------------------------------------------------

async def test_the_client_lists_and_calls_only_what_the_roles_grant(db, monkeypatch):
    from app.services import mcp_knowledge_protocol

    workspace, member = await _seeded(db)
    await db.commit()

    async def connection_workspace(server, session):
        return workspace

    @asynccontextmanager
    async def test_session():
        yield db

    monkeypatch.setattr(mcp_knowledge_protocol, "_connection_workspace", connection_workspace)
    monkeypatch.setattr(mcp_knowledge_protocol, "_connection_user", lambda server: member)
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", test_session)
    server = mcp_knowledge_protocol.build_knowledge_mcp_server()
    before = {tool.name for tool in await server.list_tools()}
    assert "work_item_create" in before, "switch off: nothing changes"

    db.add(WorkspaceWorkRoleSettings(project_id=workspace, role_based_tools=True))
    await db.commit()
    assert {tool.name for tool in await server.list_tools()} == set(), "no role, no tools"
    refused = await server.call_tool("work_item_create", {"project_id": workspace, "title": "x"})
    assert refused.isError and "no role in this Workspace" in refused.content[0].text

    await _assign(db, workspace, member, "viewer", switch=False)
    await db.commit()
    viewer = {tool.name for tool in await server.list_tools()}
    assert "knowledge_search" in viewer and "work_item_create" not in viewer and "board_post" not in viewer


# --- deciders and the product-owner gate -------------------------------------------------------------------------

async def test_the_po_gate_checks_the_function_not_a_role_name(db):
    workspace, member = await _seeded(db)
    user = await db.get(User, member)
    run = SimpleNamespace(project_id=workspace, node_state={"waiting": {"subject": "readiness"}})
    assert await po_function_refusal(db, run, user) is None, "switch off: the requester decides"
    await _assign(db, workspace, member, "engineer")
    refusal = await po_function_refusal(db, run, user)
    assert "Decide as product owner" in refusal and "Workspace admin" in refusal
    other = SimpleNamespace(project_id=workspace, node_state={"waiting": {"subject": "test_contract"}})
    assert await po_function_refusal(db, other, user) is None, "not a product owner's decision"
    await _assign(db, workspace, member, "product_manager")
    assert await po_function_refusal(db, run, user) is None


async def test_function_deciders_validate_and_seed_role_keys_resolve_through_the_new_assignments(db):
    assert validate_decider_config({"decider": "function:decide_as_po"}) == ""
    assert validate_decider_config({"decider": "function:Not Valid"}) != ""
    workspace, member = await _seeded(db)
    assert await work_role_members(db, workspace, "engineer") == ()
    await _assign(db, workspace, member, "engineer", switch=False)
    assert await work_role_members(db, workspace, "engineer") == (member,)
    grant = await effective_permission(db, member, workspace)
    assert not grant.enforced and grant.unrestricted, "an assignment alone narrows nothing"


# --- phase shell ------------------------------------------------------------------------------------------------

def test_role_command_rules_layer_on_the_workspace_command_safety():
    grant = _grant(_role("sre", allow=("npm run *",), deny=("terraform *",)))
    config = with_role_commands({"always_deny_patterns": ["rm -rf /"]}, grant)
    assert config["always_deny_patterns"] == ["rm -rf /"]
    assert role_command_allowed("npm  run build", config)
    assert not role_command_allowed("npm install", config)
    denied = role_command_denial("terraform apply -auto-approve", config)
    assert "Sre" in denied and "Workspace admin" in denied
    assert with_role_commands({"x": 1}, _grant(_role(), enforced=False)) == {"x": 1}


def test_a_role_allow_admits_a_command_the_strict_phase_shell_refuses_and_a_role_deny_refuses():
    from app.services.workflow_runs.octryx.phase_rules import _tool_decision
    from app.services.workflow_runs.octryx.tool_denial import REASON_ROLE_COMMAND

    phase = {"title": "Build", "tools": {"allow": ["bash"], "deny": []}, "path_rules": {},
             "capability_class": "read_only"}
    config = with_role_commands({}, _grant(_role("sre", allow=("npm run lint",))))
    assert _tool_decision(phase, "Bash", "npm run lint", ()) is not None, "refused without the role rule"
    assert _tool_decision(phase, "Bash", "npm run lint", (), exec_config=config) is None
    assert REASON_ROLE_COMMAND == "work_role_command_rule"
