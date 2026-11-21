from app.services.coordinator_mode_routing_policy import (
    CoordinatorRoutingSignals,
    decide_coordinator_mode,
)


def test_routes_to_deterministic_workflow_for_known_contract() -> None:
    decision = decide_coordinator_mode(CoordinatorRoutingSignals(deterministic_workflow_id="multi_source_summary"))

    assert decision.mode == "deterministic_workflow"
    assert decision.requires_manual_review is False
    assert "multi_source_summary" in decision.rationale


def test_routes_to_worker_delegation_for_explicit_worker_assignment() -> None:
    decision = decide_coordinator_mode(
        CoordinatorRoutingSignals(
            target_worker_id="worker-42",
            requested_action="diagnose",
        )
    )

    assert decision.mode == "worker_delegation"
    assert decision.conflicts == ()
    assert "explicit target worker" in decision.rationale


def test_routes_to_worker_delegation_for_domain_assignment() -> None:
    decision = decide_coordinator_mode(
        CoordinatorRoutingSignals(
            required_worker_domain="kubernetes",
            requested_action="diagnose",
        )
    )

    assert decision.mode == "worker_delegation"
    assert "kubernetes" in decision.rationale


def test_routes_to_sub_agent_group_for_parallel_child_runs() -> None:
    decision = decide_coordinator_mode(
        CoordinatorRoutingSignals(
            requires_parallel_children=True,
            expected_child_count=3,
            requires_parent_resume=True,
        )
    )

    assert decision.mode == "sub_agent_group"
    assert decision.requires_manual_review is False
    assert "multiple child runs" in decision.rationale


def test_routes_to_sub_agent_group_for_parent_resume_lifecycle() -> None:
    decision = decide_coordinator_mode(CoordinatorRoutingSignals(requires_parent_resume=True))

    assert decision.mode == "sub_agent_group"
    assert "parent session must suspend and resume" in decision.rationale


def test_returns_manual_review_for_conflicting_workflow_and_worker_signals() -> None:
    decision = decide_coordinator_mode(
        CoordinatorRoutingSignals(
            deterministic_workflow_id="multi_source_summary",
            required_worker_domain="kubernetes",
        )
    )

    assert decision.mode == "manual_review"
    assert decision.requires_manual_review is True
    assert decision.conflicts == (
        "deterministic workflow matched",
        "worker assignment matched",
    )


def test_returns_manual_review_when_no_mode_is_explicit() -> None:
    decision = decide_coordinator_mode(CoordinatorRoutingSignals())

    assert decision.mode == "manual_review"
    assert "No bounded coordinator mode matched" in decision.rationale
