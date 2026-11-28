"""The repository named in the request on the start card, and retrying a failed start with the same issue and item."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Message
from tests.chat_phased_workflow_start_support import (  # noqa: F401
    IDEA,
    _answer,
    _approval,
    _items,
    _record,
    _send,
    _workspace,
    fakes,
)
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = [pytest.mark.workflow_proposals, pytest.mark.usefixtures("scripted_pool")]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_the_repository_the_request_names_is_on_the_card_and_the_run_gets_it(client, db, auth_headers, fakes):  # noqa: F811
    state = fakes("spec-writing")
    project_id = await _workspace(db, both_coding=True)
    session_id = await _send(client, auth_headers, project_id=project_id,
                             prompt=IDEA.replace("an,", "an (Repository octryx/kitchen-helper),"))
    record = await _record(db, session_id)
    repository = record["start"]["repository"]
    assert (repository["ref"], repository["source"]) == ("bitbucket:octryx/kitchen-helper", "request")
    assert {option["ref"] for option in repository["options"]} == {"bitbucket:octryx/kitchen-helper",
                                                                   "bitbucket:shop/demo-shop"}
    assert "Repository: bitbucket:octryx/kitchen-helper." in (await _approval(db, session_id)).reason

    response = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
    assert response.status_code == 200, response.text
    [started] = state["started"]
    assert started["repository"] == "bitbucket:octryx/kitchen-helper"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_without_a_resolvable_repository_the_card_says_so_and_nothing_starts_until_one_is_chosen(
        client, db, auth_headers, fakes):  # noqa: F811
    state = fakes("spec-writing")
    project_id = await _workspace(db, both_coding=True)
    session_id = await _send(client, auth_headers, project_id=project_id)
    record = await _record(db, session_id)
    repository = record["start"]["repository"]
    assert repository["ref"] is None and repository["required"] is True
    missing = ("Choose the repository the run works in (bitbucket/projects/SHOP/repos/demo-shop, "
               "octryx/kitchen-helper).")
    assert missing in record["start"]["notes"] and missing in (await _approval(db, session_id)).reason

    refused = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
    assert refused.status_code == 409 and refused.json()["detail"] == missing
    assert (await _approval(db, session_id)).status == "pending"
    assert await _items(db, project_id) == [] and state["started"] == [] and state["jira_calls"] == []
    unknown = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply", repository="x/y")
    assert unknown.status_code == 422

    kitchen_helper = next(option for option in repository["options"] if option["name"] == "octryx/kitchen-helper")
    response = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply",
                             repository=kitchen_helper["id"])
    assert response.status_code == 200, response.text
    [started] = state["started"]
    assert started["repository"] == "bitbucket:octryx/kitchen-helper"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_failed_start_is_tried_again_by_the_next_allow_and_reuses_the_issue_and_the_item(
        client, db, auth_headers, fakes):  # noqa: F811
    state = fakes("spec-writing")
    state["refuse_run"] = "A build workflow never runs on the server."
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)
    proposal_id = (await _record(db, session_id))["proposal_id"]

    first = await _answer(client, auth_headers, session_id, proposal_id, "apply")
    assert first.status_code == 200, first.text
    record = await _record(db, session_id)
    assert record["started"]["error"] == "A build workflow never runs on the server. Press Start again to retry."
    assert record["started"]["jira"]["key"] == "CHEF-7" and record["started"]["work_item_key"] == "CHEF-7"
    assert state["started"] == []

    retry = await _answer(client, auth_headers, session_id, proposal_id, "apply")
    assert retry.status_code == 200, retry.text
    assert len(state["jira_calls"]) == 1, "the Jira issue is reused, never created twice"
    [item] = await _items(db, project_id)
    [started] = state["started"]
    assert started["work_item_id"] == item.id and item.source_key == "CHEF-7"
    record = await _record(db, session_id)
    assert "error" not in record["started"] and record["started"]["run_id"]
    posted = (await db.execute(select(Message.content).where(Message.session_id == session_id,
                                                             Message.model == "workflow-start"))).scalars().all()
    assert posted[0].endswith("did not start: A build workflow never runs on the server. Press Start again to retry.")
    assert posted[1].startswith("Created Jira Epic CHEF-7 in CHEF. Started Spec writing for Epic CHEF-7 'Hello Kitchen'.")
    again = await _answer(client, auth_headers, session_id, proposal_id, "apply")
    assert again.json()["workflowProposalDecision"] == "already_decided" and len(state["started"]) == 1
