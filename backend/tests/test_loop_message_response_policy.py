from app.agent.loops.response._loop_message_response_policy import (
    build_runtime_salvage_office_artifact_message,
    build_runtime_salvage_outline_from_evidence_message,
    build_runtime_salvage_presentation_message,
    build_runtime_salvage_weekly_summary_message,
    build_tool_execution_status_message,
)


def test_runtime_salvage_presentation_message_preserves_provider_limit_suffix():
    message = build_runtime_salvage_presentation_message(
        topic="report-builder",
        relative_path="slides/presentation.pptx",
    )

    assert "report-builder" in message
    assert "slides/presentation.pptx" in message
    assert "Core capabilities" in message
    assert "provider limit" in message


def test_runtime_salvage_outline_message_preserves_outline_structure():
    message = build_runtime_salvage_outline_from_evidence_message()

    assert "Slide 1: Overview" in message
    assert "Operational considerations" in message
    assert "provider limit" in message


def test_runtime_salvage_weekly_summary_message_keeps_domain_counts():
    message = build_runtime_salvage_weekly_summary_message(
        jira_count=2,
        bitbucket_count=3,
        confluence_count=4,
    )

    assert "- Jira: 2 relevant issues" in message
    assert "- Bitbucket: 3 relevant commits" in message
    assert "- Confluence: 4 relevant page updates" in message
    assert "provider limit" in message


def test_runtime_salvage_office_artifact_message_mentions_relative_path():
    message = build_runtime_salvage_office_artifact_message(relative_path="exports/result.pptx")

    assert "exports/result.pptx" in message
    assert "provider limit" in message


def test_tool_execution_status_message_handles_empty_single_and_multiple_inputs():
    assert build_tool_execution_status_message(tool_names=[]) == (
        "I am now processing the results that are already loaded."
    )
    assert build_tool_execution_status_message(tool_names=["  get_project_knowledge_overview  "]) == (
        "I am now gathering the missing evidence with `get_project_knowledge_overview`."
    )
    message = build_tool_execution_status_message(
        tool_names=[
            "get_project_knowledge_overview",
            "get_confluence_page",
            "list_bitbucket_repositories",
            "extra",
        ]
    )
    assert message.startswith("I am now gathering the missing evidence with `get_project_knowledge_overview`")
    assert "`get_confluence_page`" in message
    assert "`list_bitbucket_repositories`" in message
    assert message.endswith(".")
