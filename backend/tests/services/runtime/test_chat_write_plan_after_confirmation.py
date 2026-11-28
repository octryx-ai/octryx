"""After the person confirms a write plan the chat performs it; it never proposes the same plan again."""

from __future__ import annotations

import pytest

from app.services.chat_deferred_tools import CHAT_CORE_TOOLS
from app.services.run_capability.chat_write_plan import active_plan, confirmed_plan_note
from app.services.work_role_model.surfaces import with_prompt_note
from app.tools.registry import execute_tool
from tests.chat_write_plan_support import chat, writes  # noqa: F401 - fixtures
from tests.services.runtime.test_chat_write_plan import _confirm, _propose

T08_TASK = {"project_key": "CHEF", "summary": "Add rate limiting to the recipe API", "issue_type": "Task",
            "description": "limit to 100 requests per minute per user."}


@pytest.mark.asyncio
async def test_t08_the_restarted_turn_is_told_to_perform_the_confirmed_plan(db, chat, writes):  # noqa: F811
    user, session, context = chat
    await _confirm(db, user, await _propose(context, ("create_jira_ticket", T08_TASK),
                                            request="Create the Task 'Add rate limiting to the recipe API' in CHEF"))
    plan = active_plan(session.metadata_)

    note = confirmed_plan_note(session.metadata_)

    assert note is not None and plan["plan_id"] in note
    assert "do not call propose_write_plan again" in note and "create_jira_ticket" in note
    assert "Add rate limiting to the recipe API" in note
    # It reaches the model as part of the leading system message, like the role note.
    [system, user_turn] = with_prompt_note([{"role": "system", "content": "base"},
                                            {"role": "user", "content": "Create a Jira ticket"}], note)
    assert system["content"].startswith("base\n\nThe person has confirmed the write plan")
    assert user_turn["content"] == "Create a Jira ticket"


@pytest.mark.asyncio
async def test_t08_a_repeated_proposal_answers_with_the_write_to_call_and_the_write_runs_once(db, chat, writes):  # noqa: F811
    user, _session, context = chat
    await _confirm(db, user, await _propose(context, ("create_jira_ticket", T08_TASK)))

    again = await _propose(context, ("create_jira_ticket", T08_TASK))

    assert again["status"] == "confirmed" and "approval_id" not in again
    assert again["next_calls"] == [{"tool": "create_jira_ticket", "arguments": T08_TASK}]
    created = await execute_tool("create_jira_ticket", again["next_calls"][0]["arguments"], context)
    assert created["key"] == "CHEF-1" and len(writes) == 1


@pytest.mark.asyncio
async def test_t21_what_the_plan_already_did_is_never_repeated_and_the_note_ends_with_the_request(db, chat, writes):  # noqa: F811
    user, session, context = chat
    comment = {"ticket_id": "CHEF-8", "comment": "Fix ist im Commit CHEF-8 auf main."}
    await _confirm(db, user, await _propose(context, ("create_jira_ticket", T08_TASK), ("add_jira_comment", comment)))
    await execute_tool("create_jira_ticket", T08_TASK, context)

    assert "Already done by this plan (never repeat these writes): chef-1" in confirmed_plan_note(session.metadata_)

    session.metadata_ = {**session.metadata_, "current_turn_user_message_id": "request-2"}
    assert confirmed_plan_note(session.metadata_) is None, "a new request has no confirmed plan"


def test_the_most_asked_chat_writes_are_sent_in_full_without_tool_search():
    assert {"create_jira_ticket", "add_jira_comment", "propose_write_plan"} <= set(CHAT_CORE_TOOLS)
