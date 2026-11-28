"""Verification contract: resolution priority, workflow-contract application,
step-machine adaptation, and governed command execution."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.secure_work.coding.verification_contract import (
    apply_verification_contract_to_workflow_contract,
    resolve_verification_contract,
    verification_contract_prompt_lines,
)


def _unit(commands: list[str]):
    return SimpleNamespace(validation_commands_json=commands)


def _plan(validation_plan: list[dict]):
    return SimpleNamespace(validation_plan_json=validation_plan)


def test_resolution_highest_trust_source_wins():
    plan = _plan([{"command": "terraform plan", "source": "llm_inference"}, {"command": "helm lint"}])
    units = [_unit(["terraform fmt -check -recursive terraform", "test ! -d terraform/todelete"])]
    contract = resolve_verification_contract(plan=plan, units=units)

    # Unit commands define the contract; plan commands must NOT leak in —
    # a merged contract with unrunnable plan commands can never go green.
    commands = [entry["command"] for entry in contract["commands"]]
    assert commands == [
        "terraform fmt -check -recursive terraform",
        "test ! -d terraform/todelete",
    ]
    assert contract["resolved_from"] == ["change_unit"]

    # Without unit commands the plan is the source.
    fallback = resolve_verification_contract(plan=plan, units=[_unit([])])
    assert [e["command"] for e in fallback["commands"]] == ["terraform plan", "helm lint"]
    assert fallback["resolved_from"] == ["plan_validation_plan"]

    # Profile commands outrank the plan when present.
    profiled = resolve_verification_contract(
        plan=plan, units=[], profile_commands={"test_commands": ["pytest -q"]}
    )
    assert [e["command"] for e in profiled["commands"]] == ["pytest -q"]
    assert profiled["resolved_from"] == ["repository_profile"]


def test_prompt_lines_name_the_gate_and_fallback():
    lines = verification_contract_prompt_lines({"commands": [{"command": "pytest -q", "source": "change_unit"}]})
    assert any("run_validation_commands" in line for line in lines)
    assert any("pytest -q" in line for line in lines)
    fallback = verification_contract_prompt_lines({"commands": []})
    assert any("run_test_suite" in line for line in fallback)


def test_workflow_contract_application_from_session_metadata():
    contract = {"commands": [{"command": "mvn test", "source": "repository_profile"}]}
    applied = apply_verification_contract_to_workflow_contract(
        {"workflow_id": "coding_change_tdd", "topic": "x"},
        {
            "secure_work_execution": {
                "verification_contract": contract,
                "delivery": {"source_control_provider": "bitbucket", "ticket_provider": "jira"},
            }
        },
    )
    assert applied["verification_contract"] == contract
    assert applied["delivery"] == {"source_control_provider": "bitbucket", "ticket_provider": "jira"}
    untouched = apply_verification_contract_to_workflow_contract(
        {"workflow_id": "coding_change_tdd", "topic": "x"},
        {"secure_work_execution": {}},
    )
    assert "verification_contract" not in untouched
    assert "delivery" not in untouched

    # Approved expected paths flow from the prepared workspaces into the
    # contract — loop guards read them from state, never from prompt text.
    with_paths = apply_verification_contract_to_workflow_contract(
        {"workflow_id": "coding_change_tdd", "topic": "x"},
        {
            "secure_work_execution": {
                "workspaces": [
                    {"evidence": {"approved_expected_paths": ["terraform/todelete", "terraform"]}},
                    {"evidence": {"approved_expected_paths": ["terraform"]}},
                ]
            }
        },
    )
    assert with_paths["expected_paths"] == ["terraform/todelete", "terraform"]




def test_governed_coding_contract_signal():
    from app.services.secure_work.coding.verification_contract import is_governed_coding_contract

    governed = {"workflow_id": "coding_change_tdd", "verification_contract": {"commands": [{"command": "x"}]}}
    assert is_governed_coding_contract(governed)
    assert not is_governed_coding_contract({"workflow_id": "knowledge_request"})
    assert not is_governed_coding_contract({"workflow_id": "coding_change_tdd"})
    assert not is_governed_coding_contract(None)


def test_routing_never_displaces_governed_coding_contract():
    from app.services.session.turn_preparation import clear_stale_workflow_metadata

    governed = {"workflow_id": "coding_change_tdd", "verification_contract": {"commands": [{"command": "x"}]}}
    metadata = {"workflow_contract": governed}
    clear_stale_workflow_metadata(metadata, expected_workflow_id="knowledge_request")
    assert metadata["workflow_contract"] is governed
    clear_stale_workflow_metadata(metadata, expected_workflow_id="")
    assert metadata["workflow_contract"] is governed

    # non-governed contracts keep the previous stale-clearing behavior
    metadata = {"workflow_contract": {"workflow_id": "jira_release_status"}}
    clear_stale_workflow_metadata(metadata, expected_workflow_id="knowledge_request")
    assert "workflow_contract" not in metadata




def test_governed_session_routing_is_stable_across_follow_up_turns():
    from types import SimpleNamespace

    from app.services.session.turn_preparation import preserve_waiting_session_contract

    governed = {
        "workflow_id": "coding_change_tdd",
        "verification_contract": {"commands": [{"command": "x", "source": "change_unit"}]},
    }
    session = SimpleNamespace(
        status="active",
        agent_type="change",
        metadata_={
            "workflow_contract": governed,
            "routing_intent": "workflow_process",
            "routing_reason": "secure_work_execution",
            "execution_strategy": "standard_loop",
            "execution_strategy_reason": "governed_coding",
            "expected_workflow_id": "coding_change_tdd",
        },
    )
    resolved = preserve_waiting_session_contract(
        session=session,
        agent_id="",
        agent_type_explicit=False,
        routing_intent="aws_infrastructure",
        routing_reason="keyword_match",
        execution_strategy="workflow",
        execution_strategy_reason="router",
        expected_workflow_id="aws_infrastructure_lookup",
        effective_agent_type="diagnosis",
    )
    assert resolved == (
        "workflow_process",
        "secure_work_execution",
        "standard_loop",
        "governed_coding",
        "coding_change_tdd",
        "change",
    )
