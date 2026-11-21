"""Missing evidence follow-up skipping and the default agent selection for chat."""

import app.agent.core.runtime.standard_loop as standard_loop_module
from app.web._helpers._routing_default_selection import _derive_chat_default_selection


def test_diagram_requests_are_not_classified_as_coding_change_tasks():
    assert (
        standard_loop_module._is_probable_coding_change_request(
            capability_type="admin",
            user_message="Erstelle ein Architekturdiagramm für einen Microservice mit API-Gateway, Auth-Service und Datenbank.",
            workspace_root="/tmp",
        )
        is False
    )


def test_successful_knowledge_request_skips_missing_evidence_followup():
    workflow_contract = {"workflow_id": "knowledge_request", "workflow_class": "knowledge_request"}
    turn_tool_history = [
        {
            "tool_name": "knowledge_search",
            "result": {"count": 0, "results": []},
        }
    ]

    assert (
        standard_loop_module._skip_missing_evidence_for_workflow(
            workflow_contract,
            turn_tool_history=turn_tool_history,
        )
        is True
    )


def test_attempted_knowledge_request_skips_missing_evidence_followup_after_scope_error():
    workflow_contract = {"workflow_id": "knowledge_request", "workflow_class": "knowledge_request"}
    turn_tool_history = [
        {
            "tool_name": "knowledge_search",
            "result": {"error": "project_id is required when no single active project is available"},
        }
    ]

    assert (
        standard_loop_module._skip_missing_evidence_for_workflow(
            workflow_contract,
            turn_tool_history=turn_tool_history,
        )
        is True
    )


def test_derive_chat_default_selection_takes_the_primary_agent():
    selection = _derive_chat_default_selection(
        agent_options=[
            {"id": "agent-1", "name": "Engineering Agent", "agentType": "change", "isPrimary": True},
            {"id": "agent-2", "name": "Frontend Engineer Agent", "agentType": "change", "isPrimary": False},
        ],
    )

    assert selection["selected_agent_id"] == "agent-1"
    assert selection["selected_agent_name"] == "Engineering Agent"
    assert selection["selected_agent_type"] == "change"
