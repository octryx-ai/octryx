"""A chat's writes run under one plan the person confirms once per request; anything outside its scope is one
amendment."""

# ruff: noqa: F811  (the shared ``chat`` and ``writes`` fixtures are imported, then requested by name)
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import Approval, ChangePreview
from app.services.approval.resolution_service import resolve_approval_request
from app.services.run_capability import chat_write_plan
from app.services.run_capability.chat_write_plan import call_targets, uncovered
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.chat_write_plan_support import JIRA, chat, writes  # noqa: F401 - fixtures

EPIC = {"project_key": "CHEF", "issue_type": "Epic", "summary": "Kitchen helper v1"}


async def _propose(context, *planned, scope=None, request="Kitchen helper v1 in Jira"):
    params = {"request": request, "writes": [{"tool": tool, "fields": fields} for tool, fields in planned]}
    if scope:
        params["scope"] = scope
    return await execute_tool("propose_write_plan", params, context)


async def _confirm(db, user, held):
    assert held["approval_required"] is True and held["approval_status"] == "pending", held
    await resolve_approval_request(db, approval_id=held["approval_id"], resolved_by=user.id, status="approved")


async def _approvals(db) -> list[Approval]:
    return list((await db.execute(select(Approval))).scalars().all())


@pytest.mark.asyncio
async def test_a_write_without_a_plan_names_the_next_step_and_asks_nobody(db, chat, writes):
    _user, _session, context = chat

    refused = await execute_tool("create_jira_ticket", EPIC, context)

    assert refused["code"] == "write_plan_required" and refused["next_tool"] == "propose_write_plan"
    assert refused["plan_write"] == {"tool": "create_jira_ticket", "fields": EPIC}, "a ready entry for the plan"
    assert refused["tool_execution"]["category"] == "denied_by_policy"
    assert refused["tool_execution"]["policy"] == "chat_write_plan"
    assert writes == [] and await _approvals(db) == []


@pytest.mark.asyncio
async def test_one_confirmation_covers_every_write_in_the_plans_scope(db, chat, writes):
    user, _session, context = chat
    story = {"project_key": "CHEF", "issue_type": "Story", "summary": "Weekly menu", "parent_key": "CHEF-1"}

    held = await _propose(context, ("create_jira_ticket", EPIC), ("create_jira_ticket", story),
                          ("add_jira_comment", {"ticket_id": "CHEF-1", "comment": "Plan confirmed"}))
    preview = json.loads((await db.execute(select(ChangePreview).where(
        ChangePreview.id == held["change_preview_id"]))).scalar_one().preview_json)
    assert preview["kind"] == "write_plan" and [write["tool"] for write in preview["writes"]] == [
        "create_jira_ticket", "create_jira_ticket", "add_jira_comment"]
    assert {"kind": "jira_project", "value": "chef", "named_by": "writes"} in preview["scope"]
    assert any(line.startswith("write 2: ") and "create_jira_ticket" not in line for line in preview["details"])
    assert preview["title"] == "Write plan with 3 writes"
    await _confirm(db, user, held)

    assert (await execute_tool("create_jira_ticket", EPIC, context))["key"] == "CHEF-1"
    assert (await execute_tool("create_jira_ticket", story, context))["key"] == "CHEF-2"
    assert (await execute_tool("add_jira_comment", {"ticket_id": "CHEF-2", "comment": "Linked"}, context)) == {"ok": True}
    assert len(writes) == 3 and len(await _approvals(db)) == 1


@pytest.mark.asyncio
async def test_a_write_outside_the_scope_is_one_amendment_confirmed_once(db, chat, writes):
    user, _session, context = chat
    await _confirm(db, user, await _propose(context, ("create_jira_ticket", EPIC)))
    other = {"project_key": "XY", "issue_type": "Task", "summary": "Elsewhere"}

    refused = await execute_tool("create_jira_ticket", other, context)
    assert refused["code"] == "write_plan_amendment_required" and refused["outside_scope"] == ["jira_project xy"]
    unlisted = await execute_tool("add_jira_comment", {"ticket_id": "CHEF-1", "comment": "hi"}, context)
    assert unlisted["code"] == "write_plan_amendment_required" and unlisted["outside_scope"] == [
        "tool add_jira_comment"]

    amendment = await _propose(context, ("create_jira_ticket", other))
    preview = json.loads((await db.execute(select(ChangePreview).where(
        ChangePreview.id == amendment["change_preview_id"]))).scalar_one().preview_json)
    assert preview["amends"] and len(preview["writes"]) == 1 and preview["confirmed_writes"][0]["fields"] == EPIC
    await _confirm(db, user, amendment)

    assert (await execute_tool("create_jira_ticket", other, context))["key"] == "CHEF-1"
    assert (await execute_tool("create_jira_ticket", EPIC, context))["key"] == "CHEF-2", "the first plan still holds"


@pytest.mark.asyncio
async def test_what_a_plan_write_created_is_in_scope_for_the_rest_of_the_request(db, chat, writes):
    user, _session, context = chat
    item = {"title": "Kitchen helper v1", "issue_type": "epic"}
    # The model cannot know the new item's key; it plans the note without it.
    await _confirm(db, user, await _propose(context, ("work_item_create", item), ("work_item_note", {"note": "x"})))

    assert (await execute_tool("work_item_create", item, context))["source_key"] == "OCX-7"
    assert (await execute_tool("work_item_note", {"work_item": "OCX-7", "note": "Started"}, context)) == {"ok": True}
    foreign = await execute_tool("work_item_note", {"work_item": "OCX-25", "note": "x"}, context)
    assert foreign["code"] == "write_plan_amendment_required" and foreign["outside_scope"] == ["work_item ocx-25"]


@pytest.mark.asyncio
async def test_the_plan_expires_with_the_request(db, chat, writes):
    user, session, context = chat
    await _confirm(db, user, await _propose(context, ("create_jira_ticket", EPIC)))

    session.metadata_ = {**session.metadata_, "current_turn_user_message_id": "request-2"}
    await db.flush()

    assert (await execute_tool("create_jira_ticket", EPIC, context))["code"] == "write_plan_required"
    assert writes == []


@pytest.mark.asyncio
async def test_proposing_a_plan_that_is_already_confirmed_asks_nothing_again(db, chat, writes):
    user, _session, context = chat
    await _confirm(db, user, await _propose(context, ("create_jira_ticket", EPIC)))

    again = await _propose(context, ("create_jira_ticket", {**EPIC, "summary": "Another CHEF issue"}))

    assert again["status"] == "confirmed" and len(await _approvals(db)) == 1


@pytest.mark.asyncio
async def test_a_plan_lists_only_write_tools_and_needs_a_request_in_flight(db, chat):
    _user, session, context = chat

    invalid = await _propose(context, ("get_jira_ticket", {"ticket_id": "CHEF-1"}))
    assert invalid["code"] == "write_plan_invalid" and invalid["invalid"][0]["tool"] == "get_jira_ticket"
    session.metadata_ = {}
    await db.flush()
    assert (await _propose(context, ("create_jira_ticket", EPIC)))["code"] == "write_plan_no_turn"
    assert await _approvals(db) == []


@pytest.mark.asyncio
async def test_a_trusted_role_writes_without_a_plan_but_not_an_outbound_message(db, chat, writes, monkeypatch):
    _user, _session, context = chat

    async def trusted(db, user_id, workspace_id):
        return True

    monkeypatch.setattr(chat_write_plan, "trusted_for_chat", trusted)
    assert (await execute_tool("create_jira_ticket", EPIC, context))["key"] == "CHEF-1"
    outbound = await chat_write_plan.plan_decision(
        "ask_reporter_via_teams", {"ticket_id": "CHEF-1", "reporter_email": "anna@example.test", "question": "?"},
        context)
    assert outbound["code"] == "write_plan_required"


def test_coverage_is_by_tool_connection_and_named_targets():
    plan = {"writes": [{"tool": "create_bitbucket_pull_request", "connection": "Bitbucket",
                        "fields": {"repo_slug": "app", "from_branch": "feature/kitchen-helper", "to_branch": "develop"}},
                       {"tool": "ask_reporter_via_teams", "connection": None,
                        "fields": {"reporter_email": "anna@example.test"}}],
            "scope": [{"kind": "jira_project", "value": "CHEF"}], "created": []}
    pr = {"repo_slug": "app", "from_branch": "feature/kitchen-helper", "to_branch": "develop", "title": "Kitchen helper"}

    assert uncovered(plan, "create_bitbucket_pull_request", pr, "Bitbucket") == []
    assert uncovered(plan, "create_bitbucket_pull_request", {**pr, "to_branch": "main"}, "Bitbucket") == [
        "branch main"], "a default branch the plan did not name is an amendment"
    assert uncovered(plan, "create_bitbucket_pull_request", pr, "Bitbucket Cloud") == ["connection Bitbucket Cloud"]
    assert uncovered(plan, "ask_reporter_via_teams", {"reporter_email": "bob@example.test"}) == [
        "recipient bob@example.test"], "a new recipient is an amendment"
    assert call_targets({"summary": "CHEF-9 is broken", "base_branch": "main", "branch_name": "feature/x"}) == [
        ("branch", "feature/x")]


@pytest.mark.asyncio
async def test_the_plan_card_names_who_confirmed_it(db, chat, writes):
    from app.web._helpers.approval_serialization import _serialize_approval, approver_names

    user, _session, context = chat
    held = await _propose(context, ("create_jira_ticket", EPIC))
    await _confirm(db, user, held)
    approval = await db.get(Approval, held["approval_id"])

    serialized = _serialize_approval(approval, approver_name_by_id=await approver_names(db, [approval]))

    assert serialized["approvedBy"] == user.id
    assert serialized["approvedByName"] == (user.display_name or user.username)


@pytest.fixture
def jira_types(monkeypatch):
    from app.tools.jira_impl import _jira_ticket_tools

    async def effective(_context, _project_key, requested):
        return requested

    monkeypatch.setattr(_jira_ticket_tools, "_effective_issue_type", effective)


@pytest.mark.asyncio
async def test_the_plan_card_shows_the_epic_the_person_asked_for_not_the_default_task(db, chat, writes, jira_types):
    user, _session, context = chat
    asked = {"project_key": "CHEF", "issuetype": "Epic", "summary": "Hello Kitchen"}

    held = await _propose(context, ("create_jira_ticket", asked))
    preview = json.loads((await db.execute(select(ChangePreview).where(
        ChangePreview.id == held["change_preview_id"]))).scalar_one().preview_json)
    write = preview["writes"][0]
    assert write["fields"] == {"project_key": "CHEF", "issue_type": "Epic", "summary": "Hello Kitchen"}
    assert write["summary"] == "CHEF / Epic: Hello Kitchen" and write["after"]["issue_type"] == "Epic"
    await _confirm(db, user, held)

    await execute_tool("create_jira_ticket", asked, context)
    assert writes[-1][1]["project_key"] == "CHEF"


@pytest.mark.asyncio
async def test_a_write_naming_two_different_issue_types_is_refused_not_guessed(db, chat, writes):
    _user, _session, context = chat
    both = {"project_key": "CHEF", "issuetype": "Epic", "issue_type": "Task", "summary": "Hello Kitchen"}

    refused = await _propose(context, ("create_jira_ticket", both))

    assert refused["code"] == "write_plan_invalid" and "issuetype='Epic'" in refused["invalid"][0]["reason"]
    assert await _approvals(db) == []


@pytest.mark.asyncio
async def test_create_jira_ticket_reads_the_issue_type_aliases(jira_types):
    from app.tools.jira_impl._jira_issue_type_args import normalize_issue_type_args
    from app.tools.jira_impl._jira_ticket_tools import CreateJiraTicket

    assert normalize_issue_type_args({"issueType": "Epic"}) == ({"issue_type": "Epic"}, None)
    assert normalize_issue_type_args({"issuetype": {"name": "Epic"}, "issue_type": "Epic"})[0] == {"issue_type": "Epic"}
    assert normalize_issue_type_args({"summary": "x"}) == ({"summary": "x"}, None)
    context = ToolContext(user_id="u", project_ids=[], roles=["member"], session_id=None, project_config=dict(JIRA))
    shown = await CreateJiraTicket().preview({"project_key": "CHEF", "issuetype": "Epic", "summary": "S"}, context)
    assert shown["summary"] == "CHEF / Epic: S"
    refused = await CreateJiraTicket().execute({"project_key": "CHEF", "issuetype": "Epic", "issue_type": "Task",
                                                "summary": "S"}, context)
    assert refused["code"] == "jira_issue_type_conflict"


def test_a_call_waiting_for_approval_is_not_a_failed_step():
    from app.tools.results import tool_call_status

    waiting = {"error": "Waiting for the person to confirm the write plan.", "status": "awaiting_confirmation",
               "approval_required": True, "approval_status": "pending"}
    assert tool_call_status(waiting) == "awaiting_approval"
    assert tool_call_status({"error": "Approval required", "approval_required": True,
                             "approval_status": "pending"}) == "awaiting_approval"
    assert tool_call_status({"error": "boom"}) == "error"
    assert tool_call_status({"error": "rejected", "approval_required": True, "approval_status": "rejected"}) == "error"
    assert tool_call_status({"key": "CHEF-1"}) == "success"
