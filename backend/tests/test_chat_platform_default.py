"""Chat runs as the platform Assistant, strictly read-only; the picker offers Assistant and
Engineer (read-only in chat); an agent's tools_deny only narrows.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.context.context_planner import ContextPlan
from app.agent.core.context.turn_tool_surface import plan_and_record_turn_tool_surface
from app.models import AgentDefinition, Project
from app.services.run_capability import decide_run_capability
from app.services.session.agent_selection_sources import AgentSelectionSource
from app.services.session.turn_agent_selection import choose_turn_agent, no_selected_workflow
from app.services.workflow_routing.explicit_selection import explicit_mode_no_selection_resolution
from tests.phased_workflow_fixtures import admin_user
from tests.turn_preparation_support import prepare_chat_turn

pytestmark = pytest.mark.asyncio


async def _agent(db, key: str) -> AgentDefinition:
    return (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))).scalar_one()


async def _project(db) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"fresh-chat-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(project)
    await db.commit()
    return project


async def test_a_plain_turn_runs_as_the_assistant_read_only(db):
    admin, project = await admin_user(db), await _project(db)
    session, _runtime, _thinking, payload = await prepare_chat_turn(
        db=db, user=admin, prompt="What changed in the payment service?", project_id=project.id)
    assert payload["builtinKey"] == "assistant"
    metadata = session.metadata_
    assert (metadata["agent_selection_source"], metadata["agent_key"]) == ("platform_default", "assistant")
    assert payload["capabilityCeiling"] == "read_only" and payload["steps"] == []


async def test_the_engineer_can_be_picked_in_chat_and_stays_read_only(db):
    admin, project = await admin_user(db), await _project(db)
    engineer = await _agent(db, "engineer")
    session, _runtime, _thinking, payload = await prepare_chat_turn(
        db=db, user=admin, prompt="Explain the rounding code.", project_id=project.id, agent_id=engineer.id)
    assert payload["builtinKey"] == "engineer"
    assert session.metadata_["agent_selection_source"] == "explicit"
    # Its class in chat is read_only (the run boundary decides: test_chat_is_capped_read_only_…).
    assert payload["capabilityCeiling"] == "change"


async def test_a_selected_only_workspace_still_allows_the_platform_agents(db):
    admin = await admin_user(db)
    engineer = await _agent(db, "engineer")
    view = {"routing_policy": {"agent_assignment_mode": "selected_only"}, "bindings_by_kind": {"agent": []}}
    choice = await choose_turn_agent(
        db, owner_id=admin.id, agent_id=engineer.id, agent_type_explicit=False, clean_prompt="Hi", session=None,
        excludes_agent_type=no_selected_workflow, workspace_execution_view=view)
    assert (choice.agent_id, choice.selection_source) == (engineer.id, AgentSelectionSource.EXPLICIT)
    default = await choose_turn_agent(
        db, owner_id=admin.id, agent_id="", agent_type_explicit=False, clean_prompt="Hi", session=None,
        excludes_agent_type=no_selected_workflow, workspace_execution_view=view)
    assert default.selection_source == AgentSelectionSource.PLATFORM_DEFAULT


async def test_chat_is_capped_read_only_and_allow_changes_raises_nothing():
    change = {"source": "db", "status": "matched", "selection_source": "explicit_workflow_key",
              "workflow_contract": {"workflow_id": "coding_change_tdd", "capability_class": "change"}}
    capped = decide_run_capability(routing_resolution=change, requested_agent_type="chat",
                                   requested_mode_capability="diagnosis", agent_capability_ceiling="change")
    assert (capped.capability_class, capped.capped_outside_run) == ("read_only", True)
    in_run = decide_run_capability(routing_resolution={**change, "selection_source": "workflow_run"},
                                   requested_agent_type="chat", requested_mode_capability="diagnosis",
                                   agent_capability_ceiling="change")
    assert (in_run.capability_class, in_run.capped_outside_run) == ("change", False)
    asked = decide_run_capability(routing_resolution=explicit_mode_no_selection_resolution(),
                                  requested_agent_type="chat", requested_mode_capability="diagnosis",
                                  recorded_decisions={"capability_escalation": "allow_changes"})
    assert (asked.capability_class, asked.escalated) == ("read_only", False)


def _plan() -> ContextPlan:
    return ContextPlan(tier="t", include_tools=True, include_system_context=True, include_skills=False,
                       include_recent_history=True, include_summary_context=False, include_agent_blueprint=True,
                       recent_history_limit=10, system_prompt_variant="", route_reason="", token_budget=1000,
                       domains=[], tool_allowlist=None, skill_terms=[], blocked_tools=[], required_domains=[],
                       enforce_domain_coverage=False, scenario_profile_id="", scenario_profile_name="")


async def test_an_agents_tools_deny_only_narrows_the_surface():
    from types import SimpleNamespace

    plan = plan_and_record_turn_tool_surface(
        _plan(), session_id="s", session_metadata={}, current_session=None, capability_type="diagnosis",
        strategy_decision=SimpleNamespace(workflow_id="", workflow_contract={}), routing_resolution=None,
        agent_definition={"toolsDeny": ["knowledge_search"], "steps": []}, project_config={},
        capability_class="read_only")
    assert plan.tool_allowlist and "knowledge_search" not in plan.tool_allowlist
    granted = plan_and_record_turn_tool_surface(
        _plan(), session_id="s", session_metadata={}, current_session=None, capability_type="diagnosis",
        strategy_decision=SimpleNamespace(workflow_id="", workflow_contract={}), routing_resolution=None,
        agent_definition={"toolsDeny": [], "steps": []}, project_config={}, capability_class="read_only")
    assert set(plan.tool_allowlist) < set(granted.tool_allowlist)
