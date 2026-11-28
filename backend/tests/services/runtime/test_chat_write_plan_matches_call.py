"""A plan-admitted write runs with the confirmed arguments."""

from __future__ import annotations

import pytest

from app.services.run_capability.chat_write_plan import confirmed_plan_note
from app.services.run_capability.chat_write_plan_match import match_plan_write
from app.tools.registry import execute_tool
from tests.chat_write_plan_support import chat, writes  # noqa: F401 - fixtures
from tests.services.runtime.test_chat_write_plan import _confirm, _propose

T09_STORY = {"description": "Als Nutzer möchte ich Rezepte als Favoriten markieren können.", "issue_type": "Story",
             "project_key": "CHEF", "summary": "Rezepte als Favorit markieren"}
MARK = "\n\n— Written by an agent (octryx) — responsible: System Administrator."


@pytest.mark.asyncio
async def test_t09_the_story_the_person_confirmed_is_created_even_when_the_call_leaves_the_type_out(db, chat, writes):  # noqa: F811
    user, session, context = chat
    await _confirm(db, user, await _propose(context, ("create_jira_ticket", T09_STORY)))

    created = await execute_tool("create_jira_ticket", {"project_key": "CHEF", "summary": "Rezepte als Favorit markieren"},
                                 context)

    marked = {**T09_STORY, "description": T09_STORY["description"] + MARK}  # the platform's agent marker (E)
    assert writes == [("create_jira_ticket", marked)], "Jira gets the confirmed type and description"
    assert created["key"] == "CHEF-1"
    assert created["write_plan"]["filled_from_plan"] == {"description": T09_STORY["description"],
                                                         "issue_type": "Story"}
    assert "Report what each write's result says it did" in confirmed_plan_note(session.metadata_)


@pytest.mark.asyncio
async def test_t09_a_call_with_another_type_than_confirmed_is_refused_with_the_confirmed_call(db, chat, writes):  # noqa: F811
    user, _session, context = chat
    await _confirm(db, user, await _propose(context, ("create_jira_ticket", T09_STORY)))

    refused = await execute_tool("create_jira_ticket", {**T09_STORY, "issue_type": "Task"}, context)
    extra = await execute_tool("create_jira_ticket", {**T09_STORY, "priority": "Highest"}, context)

    assert refused["code"] == "write_plan_mismatch" and refused["next_calls"] == [
        {"tool": "create_jira_ticket", "arguments": T09_STORY}]
    assert refused["mismatch"] == ["issue_type: plan 'Story', call 'Task'"]
    assert refused["tool_execution"]["category"] == "denied_by_policy", "the model's next step, nobody is asked"
    assert extra["code"] == "write_plan_mismatch", "a field the person never confirmed is not added"
    assert writes == []


@pytest.mark.asyncio
async def test_an_epic_and_its_story_each_get_their_own_confirmed_fields(db, chat, writes):  # noqa: F811
    user, _session, context = chat
    epic = {"project_key": "CHEF", "issue_type": "Epic", "summary": "Household sharing", "labels": ["sharing"]}
    story = {"project_key": "CHEF", "issue_type": "Story", "summary": "Invite a household member"}
    await _confirm(db, user, await _propose(context, ("create_jira_ticket", epic), ("create_jira_ticket", story)))

    await execute_tool("create_jira_ticket", {"project_key": "CHEF", "summary": "Household sharing"}, context)
    await execute_tool("create_jira_ticket", {"project_key": "CHEF", "summary": "Invite a household member",
                                              "parent_key": "CHEF-1"}, context)

    assert writes[0][1]["issue_type"] == "Epic" and writes[0][1]["labels"] == ["sharing"]
    assert writes[1][1] == {**story, "parent_key": "CHEF-1", "description": MARK.strip()}, \
        "the new epic's key is the call's own, in scope"


def test_a_call_that_fits_two_confirmed_writes_differently_is_not_guessed():
    plan = {"plan_id": "wp_1", "writes": [
        {"tool": "create_jira_ticket", "fields": {"project_key": "CHEF", "issue_type": "Epic", "summary": "A"}},
        {"tool": "create_jira_ticket", "fields": {"project_key": "CHEF", "issue_type": "Story", "summary": "B"}}]}

    match = match_plan_write(plan, "create_jira_ticket", {"project_key": "CHEF", "summary": "C"})

    assert match.refusal is not None and len(match.refusal["next_calls"]) == 2
    # Free text and targets keep the scope rule: another comment on another issue of the plan still runs as called.
    comment = {"plan_id": "wp_2", "writes": [{"tool": "add_jira_comment",
                                              "fields": {"ticket_id": "CHEF-1", "comment": "Plan confirmed"}}]}
    other = match_plan_write(comment, "add_jira_comment", {"ticket_id": "CHEF-2", "comment": "Linked"})
    assert other.refusal is None and other.fields == {"ticket_id": "CHEF-2", "comment": "Linked"}
