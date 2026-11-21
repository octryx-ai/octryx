"""The octryx contract carries the phase's agent; outside a run the session is the read-only
Assistant; the governed gateway honours the phase agent's coding preference.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import AgentDefinition
from app.services.workflow_runs.octryx.agent_view import (
    outside_run_agent,
    phase_agent_model_refusal,
)
from app.services.workflow_runs.octryx.contract import run_contract
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace
from tests.platform_agent_publish_support import draft_edit, publish_edit

pytestmark = pytest.mark.asyncio


def _with_agent(agent: str) -> dict:
    definition = copy.deepcopy(phased_definition())
    definition["nodes"][1]["config"]["agent"] = agent
    return definition


async def _row(db, key: str) -> AgentDefinition:
    return (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))).scalar_one()


async def _run(db, agent: str):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    definition = _with_agent(agent)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=session)
    return run, session


async def test_the_contract_carries_the_phase_agent_and_its_instructions(db):
    run, _session = await _run(db, "engineer")
    contract = await run_contract(db, run)
    agent = contract["phase"]["agent"]
    engineer = await _row(db, "engineer")
    assert (agent["key"], agent["name"], agent["version"]) == ("engineer", "Engineer", 1)
    assert agent["instructions"] == engineer.system_prompt and agent["digest"].startswith("sha256:")
    # A live edit (a draft) changes nothing a run sees; a four-eyes published revision does.
    await draft_edit(db, engineer, instructions=engineer.system_prompt + "\nDraft rule.")
    unchanged = await run_contract(db, run)
    assert unchanged["phase"]["agent"] == agent
    published = await publish_edit(db, engineer, instructions=agent["instructions"] + "\nNew rule.")
    changed = await run_contract(db, run)
    assert changed["phase"]["agent"]["instructions"].endswith("New rule.")
    assert changed["phase"]["agent"]["version"] == published.revision_number
    assert changed["phase"]["agent"]["digest"] != agent["digest"] and changed["digest"] != contract["digest"]


async def test_a_run_pinned_to_a_version_without_phase_agents_has_none_in_the_contract(db):
    from app.models.runtime.flow_definition import FlowDefinitionVersion

    run, _session = await _run(db, "engineer")
    version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id)
    pinned = copy.deepcopy(version.definition_json)
    del pinned["nodes"][1]["config"]["agent"]
    version.definition_json = pinned
    await db.flush()
    assert (await run_contract(db, run))["phase"]["agent"] is None


async def test_outside_a_run_the_session_is_the_read_only_assistant(db):
    view = await outside_run_agent(db)
    assistant = await _row(db, "assistant")
    assert (view["key"], view["capability_class"], view["instructions"]) == (
        "assistant", "read_only", assistant.system_prompt)


async def test_the_governed_gateway_never_refuses_a_model_for_a_kind_of_work(db):
    """No model is released per kind of work; every admitted model may do a coding phase."""
    run, session = await _run(db, "engineer")
    assert await phase_agent_model_refusal(db, session.id, ["claude-3-5-haiku-20241022"]) is None
    assert await phase_agent_model_refusal(db, session.id, ["gemma-4-31b"]) is None
    assert await phase_agent_model_refusal(db, session.id, ["claude-sonnet-4-5"]) is None
    _general_run, general_session = await _run(db, "assistant")  # the Assistant prefers a general runtime
    assert await phase_agent_model_refusal(db, general_session.id, ["claude-3-5-haiku-20241022"]) is None
    assert await phase_agent_model_refusal(db, "no-session", ["claude-3-5-haiku-20241022"]) is None
