from app.models import Session
from app.services.session.turn_preparation import (
    clear_stale_workflow_metadata,
    preserve_waiting_session_contract,
    resolve_initial_runtime_selection,
    resolve_thinking_level,
)
from app.services.session.turn_refusals import TurnRefusalState, TurnRefusedError


def test_resolve_initial_runtime_selection_accepts_known_requested_runtime():
    selection = resolve_initial_runtime_selection(
        runtime_target_id="runtime-1",
        runtime_label_by_id={"": "Automatic", "runtime-1": "Bedrock Claude"},
        runtime_target_id_explicit=True,
    )

    assert selection.runtime_target_id == "runtime-1"
    assert selection.runtime_label == "Bedrock Claude"
    assert selection.reason == "requested"


def test_resolve_initial_runtime_selection_rejects_unknown_explicit_runtime():
    try:
        resolve_initial_runtime_selection(
            runtime_target_id="missing-runtime",
            runtime_label_by_id={"": "Automatic"},
            runtime_target_id_explicit=True,
        )
    except TurnRefusedError as exc:
        assert exc.refusal.state is TurnRefusalState.RUNTIME_TARGET_INVALID
        assert exc.refusal.detail == "Runtime target not found"
    else:
        raise AssertionError("Expected explicit unknown runtime to fail")


def test_resolve_initial_runtime_selection_preserves_implicit_unknown_runtime_fallback():
    selection = resolve_initial_runtime_selection(
        runtime_target_id="stale-runtime-query-param",
        runtime_label_by_id={"": "Automatic"},
        runtime_target_id_explicit=False,
    )

    assert selection.runtime_target_id == ""
    assert selection.runtime_label == "Automatic"
    assert selection.reason == "implicit_unknown_runtime_fallback"


def test_resolve_thinking_level_defaults_unknown_values_to_light():
    assert resolve_thinking_level("deep") == "deep"
    assert resolve_thinking_level("unexpected") == "light"
    assert resolve_thinking_level("") == "light"


def test_preserve_waiting_session_contract_uses_existing_workflow_metadata():
    session = Session(
        id="session-1",
        user_id="user-1",
        agent_type="coding",
        status="awaiting_subagents",
        metadata_={
            "routing_intent": "coding",
            "routing_reason": "existing_workflow",
            "execution_strategy": "workflow",
            "execution_strategy_reason": "existing_strategy",
            "expected_workflow_id": "delivery_workflow",
        },
    )

    result = preserve_waiting_session_contract(
        session=session,
        agent_id="",
        agent_type_explicit=False,
        routing_intent="diagnosis",
        routing_reason="new_prompt",
        execution_strategy="direct",
        execution_strategy_reason="new_strategy",
        expected_workflow_id="",
        effective_agent_type="chat",
    )

    assert result == (
        "coding",
        "existing_workflow",
        "workflow",
        "existing_strategy",
        "delivery_workflow",
        "coding",
    )


def test_preserve_waiting_session_contract_respects_explicit_agent_type():
    session = Session(
        id="session-1",
        user_id="user-1",
        agent_type="coding",
        status="awaiting_subagents",
        metadata_={"routing_intent": "coding"},
    )

    result = preserve_waiting_session_contract(
        session=session,
        agent_id="",
        agent_type_explicit=True,
        routing_intent="diagnosis",
        routing_reason="explicit",
        execution_strategy="direct",
        execution_strategy_reason="explicit",
        expected_workflow_id="",
        effective_agent_type="chat",
    )

    assert result == ("diagnosis", "explicit", "direct", "explicit", "", "chat")


def test_clear_stale_workflow_metadata_removes_mismatched_contract():
    metadata = {
        "workflow_contract": {"workflow_id": "old_workflow"},
        "current_sub_agent_group_id": "group-1",
        "sub_agent_group_id": "group-1",
    }

    clear_stale_workflow_metadata(metadata, expected_workflow_id="new_workflow")

    assert "workflow_contract" not in metadata
    assert metadata["current_sub_agent_group_id"] == "group-1"


def test_clear_stale_workflow_metadata_clears_sub_agent_state_without_expected_workflow():
    metadata = {
        "workflow_contract": {"workflow_id": "old_workflow"},
        "current_sub_agent_group_id": "group-1",
        "sub_agent_group_id": "group-1",
    }

    clear_stale_workflow_metadata(metadata, expected_workflow_id="")

    assert "workflow_contract" not in metadata
    assert "current_sub_agent_group_id" not in metadata
    assert "sub_agent_group_id" not in metadata
