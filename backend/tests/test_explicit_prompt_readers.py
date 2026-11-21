"""Turn preparation reads no prompt keywords for forced calls, coverage or grounding.

Different wordings of the same turn get the same forced calls, coverage requirements and
evidence-grounding policy; each of them has an explicit source (the selected
definition, the context plan's coverage setting, the configured high-risk agent types, the
Workspace setting). An A1-style knowledge question in plain chat gets no AWS plan, no forced
evidence and no extra contract messages.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from app.agent.core.context.evidence_grounding import resolve_evidence_grounding_policy
from app.agent.loops.outcome._loop_evidence_completion import missing_evidence_completion_action
from app.agent.loops.request._loop_workflow import plan_forced_tool_calls_for_turn
from app.agent.loops.setup._loop_bootstrap import apply_loop_bootstrap_messages
from app.agent.loops.setup._loop_setup import initialize_standard_loop_state
from app.models import Project
from app.services.request_analysis import (
    build_request_analysis_contract_message,
    required_summary_tools_from_request_analysis,
)
from app.services.workflow_contracts.contract_message import build_workflow_contract_message
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.conftest import ADMIN_PASSWORD

# Every tool a keyword path could reach for, so a missing plan is never a missing tool.
_TOOLS = [
    {"type": "function", "function": {"name": name}}
    for name in (
        "aws_read_operation",
        "list_aws_eks_clusters",
        "list_aws_codepipelines",
        "list_aws_rds_instances",
        "spawn_sub_agent",
        "knowledge_search",
        "list_jira_versions",
        "search_jira_tickets",
    )
]


def _knowledge_phase() -> dict:
    """The routing resolution of a phased workflow run phase that runs the knowledge_request contract."""
    return {
        "source": "db",
        "status": "matched",
        "selection_source": "workflow_run",
        "workflow_key": "knowledge-phase",
        "workflow_id": "knowledge_request",
        "workflow_class": "knowledge_request",
        "policy_id": None,
        "policy_version_id": None,
        "matched_group_id": None,
        "workflow_contract": {
            "workflow_id": "knowledge_request",
            "workflow_class": "knowledge_request",
            "capability_class": "read_only",
            "requires_sources": True,
            "allowed_tools": ["knowledge_search", "knowledge_read", "knowledge_changes", "memory_recall"],
        },
        "tool_policy": {"allowlist": ["knowledge_search", "knowledge_read", "knowledge_changes", "memory_recall"]},
        "safety_constraints": {"diagnosis_mode": True, "allow_mutating_tools": False},
    }


def _loop_state(prompt: str, resolution: dict | None = None, *, context_plan=None) -> dict:
    metadata = {ROUTING_RESOLUTION_KEY: copy.deepcopy(resolution)} if resolution else {}
    prepared = SimpleNamespace(
        tool_context=SimpleNamespace(project_config={"project_id": "p-w25"}, project_ids=["p-w25"]),
        context_plan=context_plan
        or SimpleNamespace(route_reason="", domains=[], required_domains=[], enforce_domain_coverage=False),
        session_metadata=metadata,
        tool_definitions=copy.deepcopy(_TOOLS),
        current_session=SimpleNamespace(metadata_={}),
    )
    return initialize_standard_loop_state(
        prepared=prepared,
        capability_type="diagnosis",
        current_turn_content=prompt,
        agent_definition=None,
        max_iterations=None,
        thinking_level=None,
        map_reasoning_effort=lambda _level: None,
    )


def _forced_calls(state: dict, prompt: str) -> list[tuple[str, dict]]:
    calls = plan_forced_tool_calls_for_turn(
        request_analysis=state["request_analysis"],
        capability_type="diagnosis",
        current_turn_content=prompt,
        workspace_root="/tmp/w25",
        current_allowed_tool_names={tool["function"]["name"] for tool in _TOOLS},
        turn_tool_history=[],
        covered_evidence_axes=set(),
        workflow_contract_from_request_analysis=lambda analysis: analysis.get("workflow_contract"),
        plan_next_workflow_tool_calls=lambda *_args, **_kwargs: [],
        _plan_coding_preflight_tool_calls=lambda **_kwargs: None,
    )
    return [(call["function"]["name"], json.loads(call["function"]["arguments"])) for call in calls or []]


def _turn_decisions(prompt: str, resolution: dict | None = None, *, project_config: dict | None = None) -> dict:
    """Everything a turn's wording must not decide: forced calls, coverage, contract messages, grounding."""
    state = _loop_state(prompt, resolution)
    analysis = state["request_analysis"]
    contract = state["workflow_contract"] or {}
    completion = missing_evidence_completion_action(
        workflow_contract=contract,
        turn_tool_history=[{"tool_name": "list_jira_versions", "result": {"versions": [{"name": "2.4.20"}]}}],
        executed_tool_names={"list_jira_versions"},
    )
    grounding = resolve_evidence_grounding_policy(
        workflow_contract=contract, agent_type="chat", project_id="p-w25", project_config=project_config
    )
    messages = apply_loop_bootstrap_messages(
        messages=[{"role": "user", "content": "<the turn>"}],
        agent_definition=None,
        injected_workflow_agent=False,
        request_analysis=analysis,
        workflow_contract=contract,
        build_request_analysis_contract_message=build_request_analysis_contract_message,
        build_workflow_contract_message=build_workflow_contract_message,
    )
    return {
        "forced_calls": _forced_calls(state, prompt),
        "aws_diagnosis_plan": analysis.get("aws_diagnosis_plan"),
        "analysis_first": analysis.get("analysis_first"),
        "requested_domains": analysis.get("requested_domains"),
        "required_domains": analysis.get("required_domains"),
        "required_summary_tools": sorted(required_summary_tools_from_request_analysis(analysis)),
        "evidence_completion": completion.tool_name if completion else None,
        "grounding": grounding.to_metadata(),
        "system_messages": [item["content"] for item in messages if item["role"] == "system"],
    }


A1_WORDINGS = [
    "What changed from Spring Boot 3 to 4?",
    "Give me an overview of what changed from Spring Boot 3 to 4: functions, architecture, deployment and operations.",
    "Summarize in a weekly report how the REST controller, the IAM role setup and the pipeline change from Spring Boot 3 to 4.",
    "Was hat sich von Spring Boot 3 zu 4 geändert? Überblick über Funktionen und Architektur, bitte.",
]
PARITY_CASES = [
    ("plain_chat", None, A1_WORDINGS),
    ("knowledge_request", "knowledge", A1_WORDINGS),
]


def _resolution_for(key: str | None) -> dict | None:
    return _knowledge_phase() if key == "knowledge" else None


@pytest.mark.parametrize(("case", "key", "wordings"), PARITY_CASES, ids=[case[0] for case in PARITY_CASES])
def test_different_wordings_of_one_turn_get_the_same_decisions(case, key, wordings):
    decisions = [_turn_decisions(prompt, _resolution_for(key)) for prompt in wordings]
    reference = {name: value for name, value in decisions[0].items() if name != "system_messages"}

    for prompt, decision in zip(wordings[1:], decisions[1:], strict=True):
        assert {name: value for name, value in decision.items() if name != "system_messages"} == reference, prompt
    # The contract messages differ at most in the request's literal parameters, never in which messages exist.
    assert {len(decision["system_messages"]) for decision in decisions} == {len(decisions[0]["system_messages"])}


def test_the_parity_cases_decide_what_their_explicit_source_says():
    plain = _turn_decisions(A1_WORDINGS[0])
    knowledge = _turn_decisions(A1_WORDINGS[0], _knowledge_phase())

    assert plain["grounding"]["applies"] is False
    assert knowledge["grounding"]["triggers"] == ["workflow_requires_sources"]


@pytest.mark.parametrize("prompt", A1_WORDINGS)
def test_an_a1_knowledge_question_in_plain_chat_is_neither_slowed_nor_narrowed(prompt):
    """Binding contract: no AWS plan, no forced or owed evidence, no extra contract message, no keyword grounding."""
    decision = _turn_decisions(prompt)

    assert decision == {
        "forced_calls": [],
        "aws_diagnosis_plan": None,
        "analysis_first": False,
        "requested_domains": [],
        "required_domains": [],
        "required_summary_tools": [],
        "evidence_completion": None,
        "grounding": {
            "applies": False,
            "triggers": [],
            "evidence_available": False,
            "evidence_sources": [],
            "reason": "no_explicit_grounding_source",
            "workspace_setting": "default",
        },
        "system_messages": [],
    }


def test_scenario_coverage_is_the_only_source_of_required_domains():
    coverage = SimpleNamespace(
        route_reason="summary_aggregation",
        domains=["jira", "confluence"],
        required_domains=["jira", "confluence"],
        enforce_domain_coverage=True,
    )
    states = [_loop_state(prompt, context_plan=coverage) for prompt in ("Weekly summary please", "Anything new?")]

    for state in states:
        analysis = state["request_analysis"]
        assert analysis["required_domains"] == ["confluence", "jira"]
        assert analysis["analysis_first"] is True
        assert "search_jira_tickets" in required_summary_tools_from_request_analysis(analysis)


def test_the_workspace_setting_grounds_plain_chat_explicitly():
    decision = _turn_decisions(A1_WORDINGS[0], project_config={"evidence_grounding_policy": {"mode": "required"}})

    assert decision["grounding"]["triggers"] == ["workspace_setting_required"]
    assert decision["forced_calls"] == []


@pytest.mark.asyncio
async def test_the_admin_ui_endpoints_validate_with_closed_codes(client, db):
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303

    route = "/admin/chat/api/panel/evidence-grounding"
    listed = (await client.get(route)).json()
    assert listed["high_risk_agent_types_source"] == "default"
    assert "knowledge" in listed["high_risk_agent_types"]
    retired = await client.put(route, json={"domain_keywords": {"ops": ["aws"]}})
    assert retired.status_code == 422
    assert retired.json()["detail"]["errors"][0]["code"] == "unknown_setting"
    saved = await client.put(route, json={"high_risk_agent_types": ["payments_analyst"]})
    assert saved.status_code == 200
    assert saved.json()["high_risk_agent_types"] == ["payments_analyst"]

    project = Project(name="w25-grounding", is_active=True)
    db.add(project)
    await db.commit()
    config_route = f"/admin/chat/api/panel/projects/{project.id}/config"
    refused = await client.put(config_route, json={"evidence_grounding_policy": {"mode": "always"}})
    assert refused.status_code == 400
    assert refused.json()["detail"]["errors"][0]["code"] == "unsupported_evidence_grounding_mode"
    stored = await client.put(config_route, json={"evidence_grounding_policy": {"mode": "required"}})
    assert stored.json()["config"]["evidence_grounding_policy"] == {"mode": "required"}
