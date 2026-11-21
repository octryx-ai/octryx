"""Roadmap item 5, last slice: the strategy path takes the workflow only from the routing resolution.

``resolve_execution_strategy`` and the standard loop build a workflow contract only for the
workflow the turn's routing resolution selected (``workflow_routing.workflow_selection``).
No workflow, an unknown key, or a pending/disabled proposal select none, recorded with a
closed reason code; the prompt never picks a family.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Session as AgentSession
from app.models import User
from app.services.execution_profile_service import build_execution_profile
from app.services.execution_strategy_intent import support_request_signature_applies
from app.services.execution_strategy_service import resolve_execution_strategy
from app.services.session import turn_start
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_prepare import prepare_turn_in_session
from app.services.session.turn_request import TurnRequest
from app.services.system_config.values import set_system_config_value
from app.services.workflow_contracts.registry import build_task_workflow_contract
from app.services.workflow_contracts.selected_contract import build_selected_workflow_contract
from app.services.workflow_routing import explicit_selection, proposal, workflow_selection
from app.services.workflow_routing.explicit_selection import (
    explicit_mode_no_selection_resolution,
    resolve_workflow_selection_for_turn,
)
from app.services.workflow_routing.platform_selection import (
    SECURE_WORK_CODING_EXECUTION,
    UnknownPlatformWorkflowServiceError,
    platform_workflow_selection_resolution,
)
from app.services.workflow_routing.proposal_states import STATUS_NEEDS_CONFIRMATION
from app.services.workflow_routing.support_signature import (
    SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY,
    SUPPORT_REQUEST_SIGNATURE_DISABLED,
)
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY, selected_workflow_analysis

# Prompts that select no workflow family without an explicit strategy: a literal typed-diagram request, a weekly
# Jira/Bitbucket/Confluence summary, and an implement-with-tests request in coding mode (coding_change_tdd).
LATCHING_PROMPTS = (
    ("Create a sequence diagram for the OAuth login flow.", "chat"),
    ("Erstelle ein Diagramm für den OAuth Login Flow als Sequenzdiagramm.", "chat"),
    ("Erstelle mir eine Wochenzusammenfassung von Änderungen in Jira, Bitbucket und Confluence.", "chat"),
    ("Implement a budget warning helper and include focused pytest tests.", "coding"),
)
PHASE_KEY = "knowledge-phase"


def _phase_resolution() -> dict:
    """The routing resolution of a workflow-run phase that runs the knowledge_request contract."""
    return {
        "source": "db",
        "status": "matched",
        "selection_source": "workflow_run",
        "workflow_key": PHASE_KEY,
        "workflow_id": "knowledge_request",
        "workflow_class": "knowledge_request",
        "policy_id": None,
        "policy_version_id": None,
        "matched_group_id": None,
        "workflow_contract": {"workflow_id": "knowledge_request", "requires_sources": True},
        "tool_policy": {},
        "safety_constraints": {},
    }


def _strategy(prompt: str, resolution: dict | None, agent_type: str = "chat", **kwargs):
    return resolve_execution_strategy(
        prompt=prompt,
        requested_agent_type=agent_type,
        agent_type_explicit=agent_type != "chat",
        workflow_routing_policy_resolution=resolution,
        **kwargs,
    )


def _loop_contract(prompt: str, resolution: dict | None, capability_type: str = "chat") -> dict:
    """The standard loop's builder call (``_loop_setup``), with the turn's resolution."""
    return build_task_workflow_contract(
        prompt,
        request_analysis=selected_workflow_analysis({"canonical_message": prompt}, resolution),
        route_reason="",
        project_id=None,
        capability_type=capability_type,
    )


def _profile(prompt: str, decision, resolution: dict | None):
    return build_execution_profile(
        prompt=prompt,
        requested_agent_type="chat",
        effective_agent_type=decision.effective_agent_type,
        execution_strategy=decision.execution_strategy,
        execution_strategy_reason=decision.execution_strategy_reason,
        routing_intent=decision.routing_intent,
        routing_reason=decision.routing_reason,
        routing_intent_confidence=decision.routing_intent_confidence,
        routing_intent_source=decision.routing_intent_source,
        workflow_id=decision.workflow_id,
        workflow_contract=decision.workflow_contract,
        workflow_routing_policy_resolution=resolution,
    ).to_metadata()


@pytest.mark.asyncio
async def test_unknown_workflow_key_with_a_diagram_prompt_infers_no_family(db):
    prompt = LATCHING_PROMPTS[0][0]
    resolution = await resolve_workflow_selection_for_turn(db, workflow_key="no-such-workflow", user_message=prompt)

    decision = _strategy(prompt, resolution)

    assert decision.workflow_id == "" and decision.workflow_contract == {}
    assert decision.workflow_selection["state"] == "unknown_key"
    assert decision.workflow_selection["reason_code"] == "unknown_workflow_key"
    assert decision.workflow_selection["workflow_key"] == "no-such-workflow"
    assert decision.execution_strategy_reason == "strategy:workflow_selection_unknown_key"
    assert _loop_contract(prompt, resolution) == {}
    # The gate still holds the turn, now for the explicit selection reason.
    profile = _profile(prompt, decision, resolution)
    assert profile["status"] == "needs_clarification"
    assert profile["workflow_id"] is None
    assert profile["policy"]["selection_reason_code"] == "unknown_workflow_key"
    assert evaluate_execution_gate(profile).status == "needs_clarification"


def test_a_workflow_run_phase_builds_exactly_its_phase_contract():
    prompt = "What is documented about the checkout flow?"
    resolution = _phase_resolution()

    decision = _strategy(prompt, resolution)

    assert decision.workflow_id == "knowledge_request"
    # The strategy runs the shared selected-contract builder (builder output plus the
    # phase's governance and provenance), the same one the loop runs.
    assert decision.workflow_contract == build_selected_workflow_contract(
        prompt, request_analysis={}, routing_resolution=resolution, route_reason=decision.routing_reason
    )
    assert decision.workflow_contract["workflow_contract_source"] == "db_routing_policy"
    assert decision.workflow_contract["requires_sources"] is True
    assert decision.workflow_selection == {
        "version": "workflow_selection.v1",
        "state": "selected",
        "reason_code": "workflow_run",
        "workflow_id": "knowledge_request",
        "workflow_key": PHASE_KEY,
    }
    # The loop builds the same family from the same resolution.
    assert _loop_contract(prompt, resolution)["workflow_id"] == "knowledge_request"


@pytest.mark.asyncio
@pytest.mark.parametrize(("prompt", "agent_type"), LATCHING_PROMPTS)
async def test_no_workflow_selects_no_contract_whatever_the_prompt_says(db, prompt, agent_type):
    resolution = await resolve_workflow_selection_for_turn(db, workflow_key="none", user_message=prompt)

    decision = _strategy(prompt, resolution, agent_type)

    assert decision.workflow_id == "" and decision.workflow_contract == {}
    assert decision.workflow_selection["state"] == "none"
    assert decision.workflow_selection["reason_code"] == "user_selected_no_workflow"
    capability = "change" if agent_type == "coding" else "chat"
    assert _loop_contract(prompt, resolution, capability) == {}


def test_a_pending_proposal_builds_no_contract():
    prompt = "Draw the checkout flow."
    # The exact shape ``proposal._propose`` returns for a pending proposal.
    pending = proposal._needs_confirmation(
        proposal._record(STATUS_NEEDS_CONFIRMATION, "confirmation_required_confidence", workflow_key=PHASE_KEY)
    )

    pending_decision = _strategy(prompt, pending)

    assert pending_decision.workflow_id == "" and pending_decision.workflow_contract == {}
    assert pending_decision.workflow_selection["state"] == "needs_confirmation"
    assert pending_decision.execution_strategy_reason == "strategy:workflow_selection_needs_confirmation"
    assert evaluate_execution_gate(_profile(prompt, pending_decision, pending)).status == "needs_confirmation"


@pytest.mark.asyncio
@pytest.mark.parametrize(("prompt", "agent_type"), LATCHING_PROMPTS)
async def test_negative_control_the_old_latching_prompts_select_nothing(db, monkeypatch, prompt, agent_type):
    """Every latch-like path, with every no-selection outcome, yields no family."""

    async def _disabled(_db, _project_id):
        return False

    monkeypatch.setattr(proposal, "workflow_proposals_enabled", _disabled)
    disabled = await resolve_workflow_selection_for_turn(db, user_message=prompt)
    assert workflow_selection.workflow_selection_from_resolution(disabled).reason_code == "proposal_disabled"
    capability = "change" if agent_type == "coding" else "chat"
    for resolution in (None, {}, explicit_mode_no_selection_resolution(), disabled):
        decision = _strategy(prompt, resolution, agent_type)
        assert decision.workflow_id == "", resolution
        assert decision.workflow_contract == {}, resolution
        assert _loop_contract(prompt, resolution, capability) == {}, resolution
    # The contract builder alone selects nothing.
    assert build_task_workflow_contract(prompt, request_analysis={}, capability_type=capability) == {}


@pytest.mark.asyncio
async def test_the_support_signature_still_decides_the_intent_behind_its_switch(db):
    """The one allowed matcher keeps its own switch and still selects no workflow."""
    prompt = "The simulation failed with a SQLServerException and a stack trace after a read timeout."
    resolution = explicit_mode_no_selection_resolution()

    on = _strategy(prompt, resolution, support_request_signature=await support_request_signature_applies(prompt, db=db))
    await set_system_config_value(
        db, key=SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY, value=SUPPORT_REQUEST_SIGNATURE_DISABLED, record_prompt_revision=False
    )
    off = _strategy(prompt, resolution, support_request_signature=await support_request_signature_applies(prompt, db=db))

    assert on.routing_intent == "support_request" and on.routing_intent_source == "signature"
    assert off.routing_intent == "diagnosis"
    assert on.workflow_id == "" and off.workflow_id == ""


@pytest.mark.asyncio
async def test_the_coding_execution_selects_its_workflow_explicitly(db):
    prompt = "Execute the approved Work Plan."
    resolution = await resolve_workflow_selection_for_turn(
        db, user_message=prompt, platform_workflow_service=SECURE_WORK_CODING_EXECUTION
    )

    decision = _strategy(prompt, resolution, "coding")

    assert resolution["source"] == "platform_service" and resolution["tool_policy"] is None
    assert decision.workflow_id == "coding_change_tdd"
    assert decision.workflow_selection["reason_code"] == "platform_service"
    assert _loop_contract(prompt, resolution, "change")["workflow_id"] == "coding_change_tdd"
    assert _profile(prompt, decision, resolution)["status"] == "allowed"
    with pytest.raises(UnknownPlatformWorkflowServiceError):
        platform_workflow_selection_resolution("chat_ui")


@pytest.mark.asyncio
async def test_a_prepared_coding_execution_turn_records_its_platform_workflow(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    request = TurnRequest(
        user_id=admin.id,
        prompt="Execute the approved Work Plan and include focused tests.",
        agent_type="coding",
        agent_type_explicit=True,
        platform_workflow_service=SECURE_WORK_CODING_EXECUTION,
    )

    prepared = await prepare_turn_in_session(db, user=admin, request=request)

    metadata = (await db.get(AgentSession, prepared.session_id)).metadata_
    assert metadata["expected_workflow_id"] == "coding_change_tdd"
    assert metadata[ROUTING_RESOLUTION_KEY]["source"] == "platform_service"
    assert metadata["execution_profile"]["policy"]["selection_reason_code"] == "platform_service"
    # No proposal call before the preparation lock for a platform service's own workflow.
    assert turn_start._prefetch_workflow_key(request) == "none"


def test_the_models_free_selection_constants_match_the_explicit_selection():
    assert workflow_selection.EXPLICIT_WORKFLOW_SELECTION_SOURCE == explicit_selection.EXPLICIT_WORKFLOW_SELECTION_SOURCE
    assert (
        workflow_selection.EXPLICIT_WORKFLOW_SELECTION_STATUS_UNKNOWN_KEY
        == explicit_selection.EXPLICIT_WORKFLOW_SELECTION_STATUS_UNKNOWN_KEY
    )
