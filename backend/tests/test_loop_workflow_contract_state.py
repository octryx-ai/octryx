"""A turn's workflow contract reuses, merges or is disabled by the session's persisted contract, and persisting writes it to the session metadata."""

from app.agent.loops.control._loop_workflow_contract_state import (
    WORKFLOW_CONTRACT_METADATA_KEY,
    persist_workflow_contract_in_session,
    resolve_workflow_contract_for_turn,
)
from app.models import Session


def test_resolve_workflow_contract_for_turn_reuses_persisted_contract_for_sub_agent_resume():
    persisted_contract = {
        "workflow_id": "research_document",
        "topic": "ticketing API integration",
        "artifact_path": "ticketing_api_integration_research_document.docx",
    }

    resolved = resolve_workflow_contract_for_turn(
        current_turn_content=(
            "Call get_context_from_subthreads, consolidate the child findings into one cited research plan, "
            "fill the document plan JSON, build the DOCX once, validate it, and then finish."
        ),
        built_workflow_contract={
            "workflow_id": "research_document",
            "topic": "Call",
            "artifact_path": "call_research_document.docx",
        },
        session_metadata={
            "current_sub_agent_group_id": "group-1",
            WORKFLOW_CONTRACT_METADATA_KEY: persisted_contract,
        },
    )

    assert resolved["topic"] == "ticketing API integration"
    assert resolved["artifact_path"] == "ticketing_api_integration_research_document.docx"
    assert resolved["subthread_context_pending"] is True
    assert resolved["sub_agents_already_spawned"] is True
    assert resolved["sub_agent_delegation_attempted"] is True


def test_persist_workflow_contract_in_session_writes_metadata():
    session = Session(id="session-1", user_id="user-1", metadata_={"title": "Live orchestration"})

    persist_workflow_contract_in_session(
        current_session=session,
        workflow_contract={
            "workflow_id": "research_document",
            "topic": "ticketing API integration",
            "subthread_context_pending": True,
        },
    )

    assert session.metadata_["workflow_contract"]["workflow_id"] == "research_document"
    assert session.metadata_["workflow_contract"]["topic"] == "ticketing API integration"
    assert "subthread_context_pending" not in session.metadata_["workflow_contract"]


def test_resolve_workflow_contract_for_turn_merges_matching_persisted_contract_flags():
    resolved = resolve_workflow_contract_for_turn(
        current_turn_content="Continue the thread from the latest assistant response.",
        built_workflow_contract={
            "workflow_id": "research_document",
            "topic": "ticketing API integration",
            "artifact_path": "ticketing_api_integration_research_document.docx",
        },
        session_metadata={
            WORKFLOW_CONTRACT_METADATA_KEY: {
                "workflow_id": "research_document",
                "topic": "ticketing API integration",
                "artifact_path": "ticketing_api_integration_research_document.docx",
                "sub_agent_delegation_attempted": True,
            }
        },
    )

    assert resolved["workflow_id"] == "research_document"
    assert resolved["sub_agent_delegation_attempted"] is True


def test_resolve_workflow_contract_for_turn_disables_workflow_when_session_blocks_it():
    resolved = resolve_workflow_contract_for_turn(
        current_turn_content="Research the main benefits of ticketing API integration.",
        built_workflow_contract={
            "workflow_id": "research_document",
            "topic": "ticketing API integration",
            "artifact_path": "ticketing_api_integration_research_document.docx",
        },
        session_metadata={"allow_workflow_contracts": False},
    )

    assert resolved == {}
