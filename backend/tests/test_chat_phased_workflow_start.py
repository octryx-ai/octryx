"""A phased workflow starts from the chat with one confirmation: the Work item and its run (``phased_start``).

Choosing spec-writing in the composer, or allowing the router's spec-writing proposal, must not answer "runs as a
workflow run for a Work item ... start it from the Work item" with nothing in the chat able to start it: the chat
does everything the client does, with ONE confirmation per task.

Only the proposal provider, the turn's model and ``start_run`` are faked (``start_run`` itself is covered by the
workflow run suites); the held turn, the approval record, the Work item and the answer endpoint are real.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Message
from app.models import Session as ChatSession
from app.services.workflow_routing.proposal_approval import PROPOSAL_APPROVAL_ACTION_PREFIX
from tests.chat_phased_workflow_start_support import (  # noqa: F401
    IDEA,
    _answer,
    _approval,
    _items,
    _record,
    _send,
    _settle,
    _workspace,
    fakes,
)

pytestmark = pytest.mark.workflow_proposals


async def _assert_started(db, state: dict, session_id: str, project_id: str, workflow_key: str, item_type: str,
                          title: str, source: str = "platform", jira_line: str = "") -> None:
    [item] = await _items(db, project_id)
    assert (item.source_type, item.issue_type, item.title) == (source, item_type, title)
    item_id, item_key = item.id, item.source_key
    [started] = state["started"]
    assert (started["workflow_key"], started["work_item_id"]) == (workflow_key, item_id)
    # Exactly like the Work item dialog: the run gets a new chat session, the default location is Automatic.
    assert started["session_id"] != session_id and started["runtime_target"] == {"kind": "auto"}
    # The run works in the Workspace's one coding repository, named like the Work item dialog's repository field.
    assert started["repository"] == "bitbucket:octryx/kitchen-helper"
    record = await _record(db, session_id)
    assert record["started"]["work_item_key"] == item_key
    assert record["started"]["href"] == f"/chat?session_id={started['session_id']}"
    posted = (await db.execute(select(Message).where(Message.session_id == session_id,
                                                     Message.model == "workflow-start"))).scalars().all()
    assert [message.content for message in posted] == [
        f"{jira_line}Started {record['start']['workflow_title']} for {record['start']['work_item']['type_label']} "
        f"{item_key} '{title}'. Follow the run: [{record['start']['workflow_title']} run]"
        f"({record['started']['href']})"]
    assert state["model_calls"] == 0, "the confirmed start never sends the request again as a chat turn"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_german_idea_proposed_as_spec_writing_starts_with_one_allow(client, db, auth_headers, fakes):  # noqa: F811
    state = fakes("spec-writing")
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)

    record = await _record(db, session_id)
    assert (record["status"], record["workflow_key"], record["phased"]) == ("needs_confirmation", "spec-writing", True)
    start = record["start"]
    assert start["work_item"] | {"description": ""} == {
        "mode": "new", "type": "epic", "type_label": "Epic", "title": "Hello Kitchen", "description": "",
        "key": None, "id": None}
    assert start["work_item"]["description"] == IDEA and start["jira_project"] == "CHEF"
    # The Jira issue is in the card's scope: one confirmation covers it.
    assert start["jira"]["label"] == "+ Jira CHEF: Epic 'Hello Kitchen'" and start["jira"]["source"] == "request"
    assert start["run_on"]["default"] == "auto" and "server" in {o["key"] for o in start["run_on"]["options"]}
    assert "Write the specification" in [step["title"] for step in start["steps"]]
    approval = await _approval(db, session_id)
    assert approval.action == f"{PROPOSAL_APPROVAL_ACTION_PREFIX}{record['proposal_id']}"
    # The held turn says what it waits for, not the proposal's generic text.
    held = (await db.execute(select(Message.content).where(Message.session_id == session_id,
                                                           Message.role == "assistant"))).scalars().all()
    assert held == ["Start Spec writing for Epic 'Hello Kitchen'? Check the draft below and press Start, choose "
                    "another workflow, or don't start."]
    # The generic approval card shows the whole start.
    assert approval.reason.startswith("Start Spec writing for a new Epic 'Hello Kitchen' (run on: Automatic). "
                                      "Repository: bitbucket:octryx/kitchen-helper. "
                                      "+ Jira CHEF: Epic 'Hello Kitchen'.")
    assert await _items(db, project_id) == [] and state["started"] == []

    response = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
    assert response.status_code == 200, response.text
    # First the Jira Epic (the normalised issue type), then the item linked to it, then the run.
    [(tool, fields)] = state["jira_calls"]
    assert (tool, fields["project_key"], fields["issue_type"], fields["summary"]) == (
        "create_jira_ticket", "CHEF", "Epic", "Hello Kitchen")
    await _assert_started(db, state, session_id, project_id, "spec-writing", "Epic", "Hello Kitchen",
                          source="jira", jira_line="Created Jira Epic CHEF-7 in CHEF. ")
    [item] = await _items(db, project_id)
    assert (item.source_key, item.source_project_key, item.source_id) == ("CHEF-7", "CHEF", "10007")
    again = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
    assert again.json()["workflowProposalDecision"] == "already_decided" and len(state["started"]) == 1


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_choosing_spec_writing_in_the_composer_holds_the_same_card_and_starts_it(
        client, db, auth_headers, fakes):  # noqa: F811
    state = fakes("spec-writing")
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id, workflow_key="spec-writing")

    record = await _record(db, session_id)
    assert (record["reason_code"], record["phased"]) == ("explicit_phased_selection", True)
    assert state["proposal"].calls == 0, "an explicit selection makes no proposal call"
    assert record["start"]["summary"] == "Start Spec writing for a new Epic 'Hello Kitchen'"

    # Allowed on the generic approval route (Claude Code gateway, admin panel): the same start.
    approval = await _approval(db, session_id)
    response = await client.post(f"/api/v1/approvals/{approval.id}/approve", json={}, headers=auth_headers)
    assert response.status_code == 200, response.text
    await _settle(session_id)
    await _assert_started(db, state, session_id, project_id, "spec-writing", "Epic", "Hello Kitchen",
                          source="jira", jira_line="Created Jira Epic CHEF-7 in CHEF. ")


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_other_workflow_shows_the_card_for_that_workflow_and_allow_starts_it(client, db, auth_headers, fakes):  # noqa: F811
    """Jira refuses here: the item stays on the platform, the run still starts, the chat names the failure."""
    state = fakes("spec-writing")
    state["jira"] = {"error": "Project 'CHEF' is not in the allowed list: ['OE']"}
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)
    proposal_id = (await _record(db, session_id))["proposal_id"]

    response = await _answer(client, auth_headers, session_id, proposal_id, "other", workflow_key="epic-delivery")
    assert response.status_code == 200, response.text
    view = response.json()["selectedSession"]["workflowProposal"]
    assert (view["workflowKey"], view["phased"], view["start"]["work_item"]["type_label"]) == (
        "epic-delivery", True, "Epic")
    approval = await _approval(db, session_id)
    assert approval.status == "pending" and approval.reason.startswith(
        "Start Story / epic delivery for a new Epic 'Hello Kitchen'")

    response = await _answer(client, auth_headers, session_id, proposal_id, "apply", run_on="server")
    assert response.status_code == 200, response.text
    [item] = await _items(db, project_id)
    assert (item.source_type, item.issue_type) == ("platform", "epic")  # the workflow's item type
    [started] = state["started"]
    assert (started["workflow_key"], started["runtime_target"]) == ("epic-delivery", {"kind": "server"})
    [posted] = (await db.execute(select(Message).where(Message.session_id == session_id,
                                                       Message.model == "workflow-start"))).scalars().all()
    assert posted.content.startswith("Jira CHEF: the Epic could not be created (Project 'CHEF' is not in the allowed "
                                     "list: ['OE']); the Work item exists on the platform only. Started Story / epic "
                                     "delivery")


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_deny_starts_nothing_and_sends_nothing_again(client, db, auth_headers, fakes):  # noqa: F811
    state = fakes("spec-writing")
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)
    proposal_id = (await _record(db, session_id))["proposal_id"]

    response = await _answer(client, auth_headers, session_id, proposal_id, "skip")
    assert response.status_code == 200, response.text
    assert await _items(db, project_id) == [] and state["started"] == [] and state["model_calls"] == 0
    db.expire_all()
    session = await db.get(ChatSession, session_id)
    assert session.metadata_["workflow_proposal_decisions"][proposal_id] == "skip"
    assert (await _approval(db, session_id)).status == "rejected"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_other_with_a_key_outside_the_persons_catalog_is_refused(client, db, auth_headers, fakes):  # noqa: F811
    fakes("spec-writing")
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)
    proposal_id = (await _record(db, session_id))["proposal_id"]

    for key in ("no-such-workflow", ""):
        response = await _answer(client, auth_headers, session_id, proposal_id, "other", workflow_key=key)
        assert response.status_code == 422, (key, response.text)
    record = await _record(db, session_id)
    assert (record["workflow_key"], record["status"]) == ("spec-writing", "needs_confirmation")
