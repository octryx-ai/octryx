"""Request analysis allowlists and language contracts, tool status and artifact-ready messages."""

from app.agent.core.runtime.standard_loop import (
    _augment_step_allowed_tools_for_request_analysis,
    _build_tool_execution_status_message,
    _build_workflow_artifact_ready_message,
)
from app.services.request_analysis.service import build_request_analysis


def test_summary_request_analysis_can_extend_step_allowlist_with_required_domain_tools():
    analysis = build_request_analysis(
        "erstelle mir eine Wochenszusammenfassung von änderungen in jira bitbucekt und confluence",
        route_reason="summary_aggregation",
        required_domains=["jira", "bitbucket", "confluence"],
        context_domains=["jira", "bitbucket", "confluence"],
        enforce_domain_coverage=True,
    )

    allowed = _augment_step_allowed_tools_for_request_analysis(
        {"search_jira_tickets", "search_confluence"},
        analysis,
    )

    assert "search_jira_tickets" in allowed
    assert "search_confluence" in allowed
    assert "list_recent_bitbucket_commits" in allowed


def test_request_analysis_leaves_the_language_to_the_model():
    message = "Erstelle mir eine Wochenzusammenfassung von Änderungen in Jira, Bitbucket und Confluence"
    analysis = build_request_analysis(
        message,
        route_reason="summary_aggregation",
        required_domains=["jira", "bitbucket", "confluence"],
        context_domains=["jira", "bitbucket", "confluence"],
        enforce_domain_coverage=True,
    )

    assert analysis["language_contract"]["output_language"] == "the language of the user's message"
    assert analysis["canonical_message"] == message  # no translation or rewriting of the user's words
    assert "summary_request" not in analysis  # No prompt-keyword summary intent


def test_tool_execution_status_message_is_nonempty_and_lists_tools():
    message = _build_tool_execution_status_message(
        [
            {"function": {"name": "knowledge_search"}},
            {"function": {"name": "get_confluence_page"}},
        ]
    )

    assert message
    assert "knowledge_search" in message
    assert "get_confluence_page" in message


def test_tool_execution_status_message_expands_batch_and_hides_meta_tools():
    message = _build_tool_execution_status_message(
        [
            {
                "function": {
                    "name": "batch",
                    "arguments": (
                        '{"invocations":[{"tool_name":"knowledge_search"},'
                        '{"tool_name":"list_bitbucket_repositories"}]}'
                    ),
                }
            },
            {"function": {"name": "load_tool_artifact"}},
        ]
    )

    assert "batch" not in message
    assert "load_tool_artifact" not in message
    assert "knowledge_search" in message
    assert "list_bitbucket_repositories" in message


def test_workflow_artifact_ready_message_mentions_artifact_and_no_more_tools():
    message = _build_workflow_artifact_ready_message({"artifact_path": "von_presentation.pptx"})

    assert "von_presentation.pptx" in message
    assert "Do not call any more tools" in message


def test_knowledge_workflow_ready_message_requests_evidence_synthesis():
    message = _build_workflow_artifact_ready_message({"workflow_id": "knowledge_request"})

    assert "Knowledge evidence phase is complete" in message
    assert "Cite Knowledge keys" in message
    assert "artifact path" not in message
