from app.agent.core.runtime.trace_runtime import build_turn_context_snapshot
from app.services.agent_definition_execution_states import (
    EXECUTION_MODE_PUBLISHED,
    PAYLOAD_MODE_KEY,
    PAYLOAD_REVISION_ID_KEY,
    PAYLOAD_REVISION_NUMBER_KEY,
    PAYLOAD_SOURCE_KEY,
    RESOLUTION_METADATA_KEY,
    SOURCE_PUBLISHED_REVISION,
)


def test_turn_context_snapshot_records_prompt_config_metadata() -> None:
    snapshot = build_turn_context_snapshot(
        system_prompt="System",
        personality_prompt="",
        memory_prompt="",
        skills_prompt="",
        summary_context_messages=[],
        history=[],
        thinking_level="light",
        runtime_target_id="runtime-1",
        system_context=None,
        agent_definition=None,
        current_step=None,
        current_step_index=0,
        prompt_config={
            "source": "db",
            "requested_variant": "bounded_evidence",
            "resolved_variant": "bounded_evidence",
            "template": {"source": "db", "checksum": "abc", "chars": 12},
        },
    )

    assert snapshot["prompt_config"]["source"] == "db"
    assert snapshot["prompt_config"]["resolved_variant"] == "bounded_evidence"
    assert snapshot["prompt_config"]["template"]["checksum"] == "abc"


def test_turn_context_snapshot_records_the_agent_definition_source() -> None:
    """The trace names which agent-definition source produced the run.

    The four provenance keys travel on the execution payload; the trace is what
    makes them durable, so a reviewer of a past turn can tell a published revision
    apart from the mutable draft row instead of assuming.
    """
    snapshot = build_turn_context_snapshot(
        system_prompt="System",
        personality_prompt="",
        memory_prompt="",
        skills_prompt="",
        summary_context_messages=[],
        history=[],
        thinking_level="light",
        runtime_target_id="runtime-1",
        system_context=None,
        agent_definition={
            "name": "Traced Agent",
            "agentType": "diagnosis",
            PAYLOAD_MODE_KEY: EXECUTION_MODE_PUBLISHED,
            PAYLOAD_SOURCE_KEY: SOURCE_PUBLISHED_REVISION,
            PAYLOAD_REVISION_ID_KEY: "revision-1",
            PAYLOAD_REVISION_NUMBER_KEY: 3,
        },
        current_step=None,
        current_step_index=0,
    )

    recorded = snapshot["agent"][RESOLUTION_METADATA_KEY]
    assert recorded["mode"] == EXECUTION_MODE_PUBLISHED
    assert recorded["source"] == SOURCE_PUBLISHED_REVISION
    assert recorded["revision_id"] == "revision-1"
    assert recorded["revision_number"] == 3


def test_turn_context_snapshot_without_an_agent_records_no_source() -> None:
    snapshot = build_turn_context_snapshot(
        system_prompt="System",
        personality_prompt="",
        memory_prompt="",
        skills_prompt="",
        summary_context_messages=[],
        history=[],
        thinking_level="light",
        runtime_target_id="runtime-1",
        system_context=None,
        agent_definition=None,
        current_step=None,
        current_step_index=0,
    )

    assert RESOLUTION_METADATA_KEY not in snapshot["agent"]
