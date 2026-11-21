"""A platform agent runs only its published, four-eyes revision — on every path.

Each test edits the live row (a draft revision, as the admin panel does) and proves that nothing a run executes
changes: the octryx run contract, the reviewer, a chat turn under the default ``draft`` execution mode, the phase
binding's runtime preference and ceiling, the gateway's coding check and the tools deny. Red before the fix.
"""

from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, AgentDefinitionRevision, Project
from app.services.agent_definition_execution import get_agent_definition_execution_mode
from app.services.agent_definition_execution_states import EXECUTION_MODE_DRAFT
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.octryx.agent_view import agent_view, phase_agent_model_refusal
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.review.reviewer_agent import reviewer_setup
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace
from tests.platform_agent_publish_support import draft_edit, publish_edit
from tests.turn_preparation_support import prepare_chat_turn

pytestmark = pytest.mark.asyncio
CANARY = "UNAPPROVED_DRAFT_CANARY"


async def _row(db, key: str) -> AgentDefinition:
    return (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))).scalar_one()


async def _published(db, row: AgentDefinition) -> AgentDefinitionRevision:
    return (await db.execute(select(AgentDefinitionRevision).where(
        AgentDefinitionRevision.definition_id == row.id, AgentDefinitionRevision.status == "published")
        .order_by(AgentDefinitionRevision.revision_number.desc()))).scalars().first()


@pytest.mark.parametrize("key", ["engineer", "assistant"])
async def test_unpublished_instructions_never_reach_octryx(db, key):
    row = await _row(db, key)
    published = await _published(db, row)
    approved = published.snapshot["definition"]["system_prompt"]
    await draft_edit(db, row, instructions=CANARY)
    view = await agent_view(db, key)
    assert (view["instructions"], view["version"]) == (approved, published.revision_number)


async def test_unpublished_reviewer_instructions_never_run(db, monkeypatch):
    row = await _row(db, "reviewer")
    approved = (await _published(db, row)).snapshot["definition"]["system_prompt"]
    await draft_edit(db, row, instructions=CANARY)

    async def no_author(*_args):
        return ""

    monkeypatch.setattr("app.services.workflow_runs.review.reviewer_agent._author_model", no_author)
    assert (await reviewer_setup(db, None)).instructions == approved


async def test_a_chat_turn_runs_the_published_assistant_even_in_the_draft_execution_mode(db):
    assert await get_agent_definition_execution_mode(db) == EXECUTION_MODE_DRAFT  # the alpha authoring default
    admin = await admin_user(db)
    project = Project(id=str(uuid.uuid4()), name=f"afs1-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(project)
    row = await _row(db, "assistant")
    await draft_edit(db, row, instructions=CANARY)
    row.tools_deny_json = '["knowledge_search"]'  # a draft narrowing never applies either
    await db.commit()
    _session, _runtime, _thinking, payload = await prepare_chat_turn(db=db, user=admin, prompt="Hello",
                                                                     project_id=project.id)
    assert payload["systemPrompt"] != CANARY and payload["toolsDeny"] == []
    assert payload["agentDefinitionSource"] == "published_revision"


async def test_phase_binding_and_gateway_use_the_published_runtime_preference_and_ceiling(db):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    definition = copy.deepcopy(phased_definition())
    definition["nodes"][1]["config"]["agent"] = "assistant"
    await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                    project_id=workspace_id, session=session)
    assistant = await _row(db, "assistant")
    # Draft: a coding preference and a change ceiling — neither may apply before a second admin publishes them.
    assistant.runtime_preference, assistant.capability_ceiling = "coding", "change"
    await draft_edit(db, assistant, instructions=assistant.system_prompt)
    resolution = await run_turn_resolution(db, session, user_message="Work on it.")
    assert not resolution["workflow_contract"].get("required_model_capability")
    assert await phase_agent_model_refusal(db, session.id, ["claude-3-5-haiku-20241022"]) is None
    # Published by a second admin: now it applies.
    await publish_edit(db, assistant, instructions=assistant.system_prompt)
    resolution = await run_turn_resolution(db, session, user_message="Work on it.")
    assert resolution["workflow_contract"]["required_model_capability"] == "coding"
    assert await phase_agent_model_refusal(db, session.id, ["claude-3-5-haiku-20241022"]) is None  # no release per work


async def test_retired_and_inactive_are_admission_switches_on_the_row(db):
    row = await _row(db, "engineer")
    row.is_active = False
    await db.flush()
    assert await agent_view(db, "engineer") is None
    row.is_active = True
    await db.flush()
    assert (await agent_view(db, "engineer"))["key"] == "engineer"


async def _unpublish(db, key: str) -> None:
    from sqlalchemy import update

    row = await _row(db, key)
    await db.execute(update(AgentDefinitionRevision).where(AgentDefinitionRevision.definition_id == row.id,
                                                           AgentDefinitionRevision.status == "published")
                     .values(status="superseded"))
    await db.flush()


async def test_a_platform_agent_without_a_published_revision_is_an_explicit_refusal_everywhere(db):
    from app.services.workflow_runs.octryx.agent_view import outside_run_agent
    from app.services.workflow_runs.octryx.contract import run_contract
    from tests.test_octryx_platform_agent import _run

    run, session = await _run(db, "engineer")
    await _unpublish(db, "engineer")
    phase = (await run_contract(db, run))["phase"]
    assert phase["agent"] is None
    assert phase["agent_refusal"] == {"state": "needs_configuration", "reason": "agent_unpublished",
                                      "agent": "engineer"}
    assert phase["tools"]["allow"] == []  # the device gets no tools for a phase whose agent cannot run
    assert await phase_agent_model_refusal(db, session.id, ["claude-sonnet-4-5"]) == "agent_unpublished"
    await _unpublish(db, "assistant")
    assistant = await outside_run_agent(db)
    assert (assistant["state"], assistant["reason"], "instructions" in assistant) == (
        "needs_configuration", "agent_unpublished", False)
    await _unpublish(db, "reviewer")
    assert await reviewer_setup(db, None) == "reviewer_agent_unpublished"
