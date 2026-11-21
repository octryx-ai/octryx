"""Binding an existing or fenced Jira epic to the phased start card instead of drafting a duplicate Work item."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import TurnTrace, User, WorkItem
from app.models.runtime.secure_work import WorkItemSyncConfig
from app.services.workflow_routing.phased_start import derived_title, named_jira_project
from tests.chat_phased_workflow_start_support import (  # noqa: F401
    IDEA,
    _answer,
    _items,
    _record,
    _send,
    _workspace,
    fakes,
)

pytestmark = pytest.mark.workflow_proposals


# The seeded Jira epic of the Kitchen helper fake (CHEF-12 "Pantry management", stories CHEF-13..CHEF-15).
PANTRY_EPIC = {"ticket_id": "CHEF-12", "summary": "Pantry management", "issue_type": "Epic",
               "description": "Track what is in the pantry.", "status": "To Do",
               "source_url": "http://fake-jira:8851/browse/CHEF-12"}


def test_the_card_draft_reads_the_named_item_and_the_jira_project_from_the_request():
    assert derived_title(IDEA) == "Hello Kitchen"
    assert named_jira_project(IDEA) == "CHEF"
    assert derived_title("Baue eine Rezeptsuche für die App. Mit Filtern.") == "Baue eine Rezeptsuche für die App"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_implementing_an_existing_jira_epic_binds_it_and_never_drafts_a_duplicate(
        client, db, auth_headers, fakes):  # noqa: F811
    """A request to "Implement the existing epic CHEF-12" routed to epic-delivery must not draft ``mode: "new"``
    titled with the prompt; Start would create a second Epic. CHEF-12 lives only in Jira here."""
    state = fakes("epic-delivery")
    state["issues"]["CHEF-12"] = PANTRY_EPIC
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id,
                             prompt="Implement the existing epic CHEF-12")

    record = await _record(db, session_id)
    item = record["start"]["work_item"]
    assert (item["mode"], item["key"], item["type_label"], item["title"]) == (
        "existing", "CHEF-12", "Epic", "Pantry management")
    assert record["start"]["jira"] is None, "an existing issue is never created again in Jira"
    assert record["start"]["summary"] == "Start Story / epic delivery for Epic CHEF-12 'Pantry management'"

    response = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
    assert response.status_code == 200, response.text
    [stored] = await _items(db, project_id)
    assert (stored.source_type, stored.source_key, stored.title) == ("jira", "CHEF-12", "Pantry management")
    assert state["jira_calls"] == [], "no Jira write: the Epic exists"
    [started] = state["started"]
    assert (started["workflow_key"], started["work_item_id"]) == ("epic-delivery", stored.id)


@pytest.mark.asyncio
@pytest.mark.committed_db  # the chat turn commits in its own session, like every start test here
async def test_a_fenced_jira_read_never_reaches_the_card_or_the_work_item(client, db, auth_headers, fakes):  # noqa: F811
    """The card must not show ``<<<summary …>>>`` markers from the fenced ``get_jira_ticket`` read, and Start must
    not copy them into the Work item. The fence is for models only."""
    state = fakes("epic-delivery")
    state["issues"]["CHEF-12"] = PANTRY_EPIC
    state["fenced"] = True
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id,
                             prompt="Implement the existing epic CHEF-12")

    record = await _record(db, session_id)
    assert record["start"]["work_item"]["title"] == "Pantry management"
    assert "<<<" not in str(record["start"])
    assert (await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")).status_code == 200
    [stored] = await _items(db, project_id)
    assert stored.title == "Pantry management" and "<<<" not in str(stored.description or "")


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_german_request_for_a_stored_epic_binds_that_item_and_starts_it_without_a_second_one(
        client, db, auth_headers, fakes):  # noqa: F811
    """A request in German to implement epic CHEF-12. The Workspace's work items hold CHEF-12 (synced from Jira):
    the card binds that row, Jira is not even read, and Allow starts the run on it."""
    state = fakes("epic-delivery")
    project_id = await _workspace(db)
    synced = WorkItem(project_id=project_id, source_type="jira", source_instance="default", source_key="CHEF-12",
                      source_project_key="CHEF", title="Pantry management", issue_type="Epic", work_state="intake")
    db.add(synced)
    await db.commit()
    synced_id = synced.id
    session_id = await _send(client, auth_headers, project_id=project_id, prompt="Setz das Epic CHEF-12 um")

    record = await _record(db, session_id)
    item = record["start"]["work_item"]
    assert (item["mode"], item["key"], item["id"], item["title"]) == ("existing", "CHEF-12", synced_id,
                                                                      "Pantry management")
    assert state["jira_reads"] == []
    response = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
    assert response.status_code == 200, response.text
    assert [row.id for row in await _items(db, project_id)] == [synced_id]
    assert [started["work_item_id"] for started in state["started"]] == [synced_id]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_key_jira_cannot_read_still_drafts_a_new_item(client, db, auth_headers, fakes):  # noqa: F811
    """Only a readable item is bound: a key-like token that is no issue (``UTF-8``) leaves the new-item draft."""
    state = fakes("epic-delivery")
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id,
                             prompt="Build UTF-8 safe recipe import.")
    item = (await _record(db, session_id))["start"]["work_item"]
    assert (item["mode"], item["key"], item["title"]) == ("new", None, "Build UTF-8 safe recipe import")
    assert state["jira_reads"] == ["UTF-8"]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_jira_connected_workspace_puts_the_epic_in_scope_and_the_held_turn_reads_started(
        client, db, auth_headers, fakes):  # noqa: F811
    """No Jira project in the request: the Workspace's one Jira intake (CHEF) and spec-writing writing the stories to
    Jira put the Epic into the card. After Allow the held turn's summary reads "started", not "needs confirmation"."""
    state = fakes("spec-writing")
    project_id = await _workspace(db)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    db.add(WorkItemSyncConfig(name="CHEF intake", project_id=project_id, source_type="jira",
                              source_instance="jira-cloud", connection_id="jira-cloud",
                              filters_json={"project_keys": ["CHEF"]}, created_by=admin.id))
    await db.commit()
    session_id = await _send(client, auth_headers, project_id=project_id,
                             prompt="Schreib die Spezifikation für 'Hello Kitchen' und setz sie um.")
    record = await _record(db, session_id)
    assert record["start"]["jira"]["label"] == "+ Jira CHEF: Epic 'Hello Kitchen'"
    assert record["start"]["jira"]["source"] == "workspace"
    trace_id = (await db.execute(select(TurnTrace.id).where(TurnTrace.session_id == session_id))).scalars().first()

    async def held_turn() -> dict:
        summary = await client.get(f"/chat/api/turn-traces/{trace_id}/execution-summary", headers=auth_headers)
        assert summary.status_code == 200, summary.text
        return summary.json()

    async def state_of_held_turn() -> str:
        return (await held_turn())["state"]

    before = await held_turn()
    assert before["state"] == "needs_confirmation"
    assert before["next_action"] == {"kind": "confirm_workflow_proposal",
                                     "label": "Start the run, choose another workflow, or don't start."}
    response = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
    assert response.status_code == 200, response.text
    [item] = await _items(db, project_id)
    # Linked like the Jira sync stores it: the intake's source instance, never a second row for CHEF-7.
    assert (item.source_type, item.source_instance, item.source_key) == ("jira", "jira-cloud", "CHEF-7")
    assert await state_of_held_turn() == "started"
    assert [fields["project_key"] for _tool, fields in state["jira_calls"]] == ["CHEF"]
