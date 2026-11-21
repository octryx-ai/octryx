"""The loop runs the same workflow contract as the strategy path for a selected workflow-run phase.

Both paths call ``selected_contract.build_selected_workflow_contract`` (builder output plus the
phase definition's governance and provenance), and the loop persists that same contract.
"""

from __future__ import annotations

import pytest

from app.services.workflow_contracts.contract_message import build_workflow_contract_message
from app.services.workflow_contracts.selected_contract import DEFINITION_GOVERNED_FIELDS
from tests.loop_contract_parity_support import (
    LOOP_STAGE_FIELDS,
    _loop_turn,
    _resolution,
    _strategy_contract,
    _without_loop_stage,
)

_KNOWLEDGE_TOOLS = ["knowledge_search", "knowledge_read", "knowledge_changes", "memory_recall"]
_KNOWLEDGE = _resolution(
    "knowledge_request",
    "knowledge_request",
    key="knowledge-phase",
    tool_policy={"allowlist": _KNOWLEDGE_TOOLS},
    safety_constraints={"diagnosis_mode": True, "allow_mutating_tools": False},
    capability_class="read_only",
    requires_sources=True,
    allowed_tools=_KNOWLEDGE_TOOLS,
)
_CODING = _resolution(
    "coding_change_tdd",
    "coding_change_tdd",
    key="coding-phase",
    capability_class="change",
    routing_intent="coding",
    required_model_capability="coding",
)

# (family, resolution, prompt, strategy agent type, loop agent-mode capability)
FAMILY_CASES = [
    ("knowledge_request", _KNOWLEDGE, "What is documented about Report Builder rollback?", "chat", "diagnosis"),
    ("knowledge_request/documentation_mode", _KNOWLEDGE, "Simulation timed out with error 504, what is known?", "documentation", "change"),
    ("coding_change_tdd", _CODING, "Add a budget warning helper with tests", "coding", "change"),
]


@pytest.mark.parametrize(("family", "resolution", "prompt", "agent_type", "capability"), FAMILY_CASES, ids=[case[0] for case in FAMILY_CASES])
def test_the_loop_runs_the_strategy_contract_for_every_family(family, resolution, prompt, agent_type, capability):
    strategy = _strategy_contract(prompt, resolution, agent_type)
    loop, persisted = _loop_turn(prompt, resolution, capability)

    assert strategy["workflow_id"] == resolution["workflow_id"]
    assert _without_loop_stage(loop) == strategy
    assert set(loop) - set(strategy) <= LOOP_STAGE_FIELDS
    # The persisted contract is the one the loop runs.
    assert persisted == loop
    # Governance and provenance of the selected definition ride on both.
    assert strategy["workflow_class"] == resolution["workflow_class"]
    assert strategy["workflow_contract_source"] == "db_routing_policy"
    assert strategy["workflow_routing_policy_id"] == resolution["policy_id"]
    assert strategy["workflow_routing_policy_version_id"] == resolution["policy_version_id"]
    assert strategy["phases"]
    configured = resolution["workflow_contract"]
    for field in DEFINITION_GOVERNED_FIELDS & set(configured):
        assert strategy[field] == configured[field]
    # The contract message the model reads is the same on both paths.
    assert build_workflow_contract_message(loop) == build_workflow_contract_message(strategy)


def test_a_knowledge_phase_builds_one_contract_on_both_paths():
    prompt = "What is documented about Report Builder rollback?"

    strategy = _strategy_contract(prompt, _KNOWLEDGE)
    loop, persisted = _loop_turn(prompt, _KNOWLEDGE)

    assert _without_loop_stage(loop) == strategy
    assert persisted == loop
    assert strategy["knowledge_query"] == "documented about Report Builder rollback"
    assert strategy["allowed_tools"] == _KNOWLEDGE_TOOLS
