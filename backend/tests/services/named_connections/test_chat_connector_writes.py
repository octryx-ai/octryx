"""A chat writes through its connections, confirmed by the person: surface, routing and preview guarantees
(the write plan itself is in ``tests/services/runtime/test_chat_write_plan.py``)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import Approval, ChangePreview, User
from app.models import Session as AgentSession
from app.services.approval.resolution_service import resolve_approval_request
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.run_capability.chat_writes import chat_platform_write_needs_confirmation
from app.services.run_capability.escalation import capability_dispatch_refusal
from app.tools.context import ToolContext
from app.tools.jira_impl._jira_helpers_ticket import _maybe_block_change_with_approval
from app.tools.registry import TOOL_REGISTRY, execute_tool
from tests.chat_connector_writes_support import CHAT_STATE, EPIC, JIRA, PHASE_STATE
from tests.knowledge_evidence_text_support import unfenced

MARK = "\n\n— Written by an agent (octryx) — responsible: System Administrator."


@pytest.fixture
async def chat_session(db):
    user = (await db.execute(select(User))).scalars().first()
    session = AgentSession(id="chat-connector-write-session", user_id=user.id, agent_type="chat", status="active",
                           metadata_={"current_turn_user_message_id": "request-1"})
    db.add(session)
    await db.flush()
    return user, session


@pytest.fixture
def jira_calls(monkeypatch):
    calls: list[dict] = []

    async def execute(params, context):
        blocked = await _maybe_block_change_with_approval("create_jira_ticket", params, context,
                                                          action_title="Create Jira ticket in CHEF")
        if blocked is not None:
            return blocked
        calls.append(dict(params))
        return {"key": "CHEF-1"}

    monkeypatch.setattr(TOOL_REGISTRY["create_jira_ticket"], "execute", execute)
    return calls


def _chat_context(user, session, db, state=CHAT_STATE) -> ToolContext:
    return ToolContext(user_id=user.id, project_ids=[], roles=["member"], session_id=session.id,
                       project_config=dict(JIRA), db=db, agent_mode_key="diagnosis", capability_type="diagnosis",
                       run_capability=dict(state))


async def _propose(context, *writes, request="Create the Kitchen helper v1 Epic"):
    return await execute_tool("propose_write_plan", {"request": request, "writes": [
        {"tool": tool, "fields": fields} for tool, fields in writes]}, context)


async def _preview(db, held) -> dict:
    row = (await db.execute(select(ChangePreview).where(ChangePreview.id == held["change_preview_id"]))).scalar_one()
    return json.loads(row.preview_json)


# The Workspace default Jira is the on-prem "Jira (Standard)"; CHEF is bound to the Cloud connection.
CLOUD = "https://kitchen-helper.atlassian.example.test"


MM_ON_CLOUD = ResolvedNamedConnection("id-cloud", "jira", "Jira", "workspace", frozenset({"CHEF"}),
                                      {"jira_url": CLOUD, "jira_token": "t-cloud"})


ROUTED_JIRA = {**JIRA, NAMED_CONNECTIONS_KEY: NamedConnectionRoutes((MM_ON_CLOUD,))}


@pytest.mark.asyncio
async def test_a_chat_create_jira_ticket_runs_after_the_person_confirmed_its_plan_once(db, chat_session, jira_calls):
    user, session = chat_session
    context = _chat_context(user, session, db)

    unplanned = await execute_tool("create_jira_ticket", EPIC, context)
    assert unplanned["code"] == "write_plan_required" and jira_calls == []
    assert (await db.execute(select(Approval))).scalars().all() == [], "nobody is asked for an unplanned write"

    held = await _propose(context, ("create_jira_ticket", EPIC))
    assert held["approval_required"] is True and held["approval_status"] == "pending"
    payload = await _preview(db, held)
    assert payload["kind"] == "write_plan" and payload["standing_rule"] is None
    write = payload["writes"][0]
    assert write["after"]["summary"] == "Kitchen helper v1"
    assert {"tool: create_jira_ticket", "connector: jira", "project_key: CHEF", "issue_type: Epic",
            "description: Kitchen helper v1 as a local web app."} <= set(write["details"])

    await resolve_approval_request(db, approval_id=held["approval_id"], resolved_by=user.id, status="approved")
    done = await execute_tool("create_jira_ticket", EPIC, context)
    # The platform marks the agent's text with the responsible person (anti-slop E).
    assert done.get("key") == "CHEF-1" and jira_calls == [{**EPIC, "description": EPIC["description"] + MARK}]
    again = await execute_tool("create_jira_ticket", {**EPIC, "summary": "Kitchen helper v1 story"}, context)
    assert again.get("key") == "CHEF-1" and len(jira_calls) == 2, "the plan covers its writes without asking again"


@pytest.mark.asyncio
async def test_a_declined_chat_write_plan_does_not_run(db, chat_session, jira_calls):
    user, session = chat_session
    context = _chat_context(user, session, db)

    held = await _propose(context, ("create_jira_ticket", EPIC))
    await resolve_approval_request(db, approval_id=held["approval_id"], resolved_by=user.id, status="rejected")
    retried = await execute_tool("create_jira_ticket", EPIC, context)

    assert jira_calls == [] and retried["code"] == "write_plan_required"
    statuses = {row.id: row.status for row in (await db.execute(select(Approval))).scalars().all()}
    assert statuses[held["approval_id"]] == "rejected"


@pytest.mark.asyncio
async def test_reads_stay_free_and_a_workflow_phase_keeps_its_class(db, chat_session, monkeypatch):
    user, session = chat_session
    read_calls: list[str] = []

    async def read(params, context):
        read_calls.append(params["ticket_id"])
        return {"key": params["ticket_id"]}

    monkeypatch.setattr(TOOL_REGISTRY["get_jira_ticket"], "execute", read)
    read_result = await execute_tool("get_jira_ticket", {"ticket_id": "CHEF-1"}, _chat_context(user, session, db))
    assert unfenced(read_result) == {"key": "CHEF-1"} and read_calls == ["CHEF-1"]

    phase_context = _chat_context(user, session, db, PHASE_STATE)
    phase = await execute_tool("create_jira_ticket", EPIC, phase_context)
    assert phase["tool_execution"]["category"] == "denied_by_policy"
    assert phase["tool_execution"]["policy"] == "project_tool_policy_explicit_allow"
    assert capability_dispatch_refusal("create_jira_ticket", phase_context)["capability_refusal"][
        "required_capability"] == "deliver"
    assert (await db.execute(select(Approval))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_chat_platform_write_needs_the_confirmed_plan_too(db, chat_session, monkeypatch):
    user, session = chat_session
    created: list[dict] = []

    async def create(params, context):
        created.append(dict(params))
        return {"source_key": "OCX-1"}

    monkeypatch.setattr(TOOL_REGISTRY["work_item_create"], "execute", create)
    item = {"title": "Kitchen helper v1", "issue_type": "epic"}
    context = _chat_context(user, session, db)

    refused = await execute_tool("work_item_create", item, context)
    assert refused["code"] == "write_plan_required" and created == []
    held = await _propose(context, ("work_item_create", item))
    payload = await _preview(db, held)
    assert payload["standing_rule"] is None
    assert {"tool: work_item_create", "title: Kitchen helper v1"} <= set(payload["writes"][0]["details"])

    await resolve_approval_request(db, approval_id=held["approval_id"], resolved_by=user.id, status="approved")
    assert (await execute_tool("work_item_create", item, context)) == {"source_key": "OCX-1"} and created == [item]


def test_only_a_chats_platform_writes_are_asked_and_reads_and_the_cli_keep_their_own_rules():
    chat = ToolContext(user_id="u1", project_ids=[], roles=["member"], session_id="s1", project_config={},
                       run_capability=dict(CHAT_STATE))
    phase = ToolContext(user_id="u1", project_ids=[], roles=["member"], session_id="s1", project_config={},
                        run_capability=dict(PHASE_STATE))
    assert chat_platform_write_needs_confirmation("work_item_note", chat)
    assert chat_platform_write_needs_confirmation("memory_remember", chat)
    assert not chat_platform_write_needs_confirmation("work_item_create", phase)
    assert not chat_platform_write_needs_confirmation("work_item_context", chat), "reads stay free"
    assert not chat_platform_write_needs_confirmation("run_cli_command", chat), "the CLI keeps its command policy"
    assert not chat_platform_write_needs_confirmation("create_jira_ticket", chat), "connector writes: own rule"


@pytest.mark.asyncio
async def test_a_chat_write_on_a_connection_that_does_not_serve_the_scope_is_refused_before_asking(
    db, chat_session, jira_calls
):
    user, session = chat_session
    context = _chat_context(user, session, db)
    context.project_config = dict(ROUTED_JIRA)

    refused = await execute_tool("create_jira_ticket", {**EPIC, "connection": "default"}, context)
    assert refused["code"] == "connection_scope_mismatch" and "'Jira'" in refused["hint"]
    planned = await _propose(context, ("create_jira_ticket", {**EPIC, "connection": "default"}))
    assert planned["code"] == "connection_scope_mismatch" and "'Jira'" in planned["hint"]
    assert (await db.execute(select(Approval))).scalars().all() == [] and jira_calls == []


@pytest.mark.asyncio
async def test_the_confirmation_names_the_bound_connection_and_the_issue_type_jira_gets(
    db, chat_session, jira_calls, monkeypatch
):
    from app.tools.jira_impl import _jira_ticket_tools

    asked: list[tuple[str, str]] = []

    async def resolve(client, jira_url, *, headers, project_key, desired_name):
        asked.append((jira_url, desired_name))
        return "Improvement"

    monkeypatch.setattr(_jira_ticket_tools, "_jira_resolve_issue_type_name", resolve)
    user, session = chat_session
    context = _chat_context(user, session, db)
    context.project_config = dict(ROUTED_JIRA)
    epic_without_type = {key: value for key, value in EPIC.items() if key != "issue_type"}

    held = await _propose(context, ("create_jira_ticket", epic_without_type))
    write = (await _preview(db, held))["writes"][0]
    details = set(write["details"])
    assert write["connection"] == "Jira"
    assert asked == [(CLOUD, "Task")]
    assert {"connection: Jira", "issue type: Improvement", "CHEF has no issue type 'Task'; Jira gets 'Improvement'."} <= details
