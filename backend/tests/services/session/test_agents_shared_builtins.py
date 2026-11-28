"""A3: Workspace-shared agents, the capability ceiling, default workflow."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, UserProject
from app.services.agent_visibility import agent_access
from app.services.run_capability.resolution import decide_run_capability
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_project, make_user


def _change_workflow() -> dict:
    return {
        "source": "db",
        "status": "matched",
        "workflow_key": "change-it",
        "workflow_contract": {"workflow_id": "coding_change_tdd", "capability_class": "change"},
        "selection_source": "workflow_run",
    }


@pytest.mark.asyncio
async def test_workspace_members_see_and_workspace_admins_edit_a_workspace_agent(db):
    owner = await make_user(db, label="agent-owner")
    member = await make_user(db, label="agent-member")
    ws_admin = await make_user(db, label="agent-ws-admin")
    outsider = await make_user(db, label="agent-outsider")
    project = await make_project(db)
    db.add_all([
        UserProject(user_id=member.id, project_id=project.id, role="member"),
        UserProject(user_id=ws_admin.id, project_id=project.id, role="admin"),
    ])
    agent = await make_definition(db, owner=owner, steps=0, project_id=project.id)
    await db.flush()

    async def visible(user_id: str) -> bool:
        clause = (await agent_access(db, user_id)).visible_clause()
        return (await db.execute(select(AgentDefinition.id).where(AgentDefinition.id == agent.id, clause))).first() is not None

    assert await visible(member.id) and await visible(ws_admin.id) and await visible(owner.id)
    assert not await visible(outsider.id)
    assert (await agent_access(db, ws_admin.id)).can_edit(agent)
    assert not (await agent_access(db, member.id)).can_edit(agent)


def test_the_agent_ceiling_caps_a_change_workflow_and_never_grants():
    capped = decide_run_capability(
        routing_resolution=_change_workflow(), requested_agent_type="chat", requested_mode_capability="diagnosis",
        agent_capability_ceiling="read_only",
    )
    assert (capped.capability_class, capped.capped_by_agent) == ("read_only", True)
    assert capped.to_metadata()["agent_ceiling"] == "read_only"
    allowed = decide_run_capability(
        routing_resolution=_change_workflow(), requested_agent_type="chat", requested_mode_capability="diagnosis",
        agent_capability_ceiling="deliver",
    )
    assert (allowed.capability_class, allowed.capped_by_agent) == ("change", False)
    no_workflow = decide_run_capability(
        routing_resolution={"source": "workflow_routing_policy", "status": "unmatched"},
        requested_agent_type="chat", requested_mode_capability="diagnosis", agent_capability_ceiling="deliver",
    )
    assert no_workflow.capability_class == "read_only"


@pytest.mark.asyncio
async def test_an_explicitly_chosen_agent_brings_no_default_workflow(db):
    from tests.turn_preparation_support import prepare_chat_turn

    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin, steps=0)
    agent.default_workflow_key = "knowledge-request-routing"
    await db.commit()
    session, _runtime, _thinking, _payload = await prepare_chat_turn(
        db=db, user=admin, prompt="Summarize it.", agent_id=agent.id)
    resolution = session.metadata_["workflow_routing_policy_resolution"]
    assert resolution.get("workflow_key") != "knowledge-request-routing"


@pytest.mark.asyncio
async def test_a_turn_in_one_workspace_never_runs_or_mentions_another_workspaces_agent(db):
    from app.services.session.turn_agent_mention import resolve_mentioned_agent_id
    from app.services.session.turn_agent_selection import resolve_turn_agent_definition
    from app.services.session.turn_refusals import TurnRefusedError

    member = await make_user(db, label="two-ws-member")
    project_a, project_b = await make_project(db), await make_project(db)
    db.add_all([
        UserProject(user_id=member.id, project_id=project_a.id, role="member"),
        UserProject(user_id=member.id, project_id=project_b.id, role="member"),
    ])
    agent_a = await make_definition(db, owner=member, steps=0, project_id=project_a.id, name="Claims Helper")
    agent_b = await make_definition(db, owner=member, steps=0, project_id=project_b.id, name="Billing Helper")
    await db.flush()

    resolution, _payload = await resolve_turn_agent_definition(
        db, agent_id=agent_a.id, owner_id=member.id, project_id=project_a.id
    )
    assert resolution.definition_id == agent_a.id
    with pytest.raises(TurnRefusedError):
        await resolve_turn_agent_definition(db, agent_id=agent_b.id, owner_id=member.id, project_id=project_a.id)
    assert await resolve_mentioned_agent_id(
        db, owner_id=member.id, prompt="@Billing Helper please", project_id=project_a.id
    ) == ""
    assert await resolve_mentioned_agent_id(
        db, owner_id=member.id, prompt="@Claims Helper please", project_id=project_a.id
    ) == agent_a.id
    assert await resolve_mentioned_agent_id(db, owner_id=member.id, prompt="@Billing Helper", project_id=None) == agent_b.id
