"""Run completion guards: no-op step completion, transitional and non-substantive assistant replies, and repeated-summary detection."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    _assistant_no_tool_response_signature,
    _assistant_no_tool_response_similarity,
    _is_transitional_assistant_response,
    _looks_like_step_completion_summary,
    run_agent,
)
from app.models import Project, Session, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_allows_document_updater_noop_completion_without_confluence_write(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    agent_definition = {
        "name": "Document Updater",
        "branchPrefix": "octryx",
        "steps": [
            {
                "name": "Update Confluence",
                "isEnabled": True,
                "stepType": "change",
                "instructions": "Apply the required changes to the approved Confluence pages precisely and traceably.",
                "successCriteria": "The affected pages were updated, or there is a clear justification why no change was possible.",
                "allowedTools": [
                    "get_confluence_page",
                    "update_confluence_page",
                    "create_confluence_page",
                ],
            }
        ],
    }

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return (
            {
                "content": (
                    "## Step Completion: Confluence Update Assessment\n\n"
                    "Status: No Confluence updates performed.\n\n"
                    "Justification: The existing report-builder pages already "
                    "cover the identified changes sufficiently."
                ),
                "tool_calls": None,
                "model": "claude-haiku-4.5",
                "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            },
            runtimes[0],
        )

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        raise AssertionError("No Confluence write tool should run for a justified no-op completion")

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Check the latest report-builder changes and assess the documentation need.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)

    assert events[-1].content.startswith("## Step Completion: Confluence Update Assessment")


def test_transitional_assistant_response_catches_future_work_updates():
    assert _is_transitional_assistant_response(
        "Step 2 complete. I have gathered sufficient evidence, identified the affected Confluence pages, "
        "summarized the documentation scope, and I am ready to proceed to Step 3. Would you like me to continue "
        "with updating the identified pages?",
        None,
        True,
    )
    assert _is_transitional_assistant_response(
        "Let me use git_change_summary to get a better view of the recent changes.",
        None,
        True,
    )
    assert _is_transitional_assistant_response(
        "Now I'll analyze the remaining repositories to extract comprehensive knowledge.",
        None,
        True,
    )
    assert _is_transitional_assistant_response(
        "I need to analyze the remaining repositories. Let me prepare them one by one.",
        None,
        True,
    )
    assert _is_transitional_assistant_response(
        "Based on my analysis of recent commits, I've identified the key changes around report-builder:\n\n"
        "**Key Changes Identified:**\n"
        "1. Version updates\n"
        "2. Configuration refactoring\n\n"
        "Now let me check existing Confluence documentation to determine if updates are needed.",
        None,
        True,
    )
    assert not _is_transitional_assistant_response(
        "The requested release **ai-release-02** has been successfully created in the Jira project **ACME**. "
        "Four tickets were created and assigned to **alice**. Let me know if you need the release to be marked as completed.",
        None,
        True,
    )


def test_transitional_tool_call_preamble_is_detected():
    from app.agent.core.guards.response_guards import is_transitional_tool_call_preamble

    assert is_transitional_tool_call_preamble(
        "Let me read the main category pages to understand the complete structure.",
        [{"id": "call-1", "function": {"name": "get_confluence_page", "arguments": "{}"}}],
    )
    assert is_transitional_tool_call_preamble(
        "I will check the latest changes for report-builder. First I fetch the relevant commits from Bitbucket.",
        [{"id": "call-2", "function": {"name": "list_recent_bitbucket_commits", "arguments": "{}"}}],
    )
    assert is_transitional_tool_call_preamble(
        "## Step 3/3: Confluence Update - Completed\n\nNo documentation updates required.",
        [{"id": "call-6", "function": {"name": "get_confluence_page", "arguments": "{}"}}],
    )


def test_allows_noop_step_completion_for_documented_justification():
    from app.agent.core.guards.response_guards import allows_noop_step_completion

    step = {
        "name": "Update Confluence",
        "instructions": "Apply the required changes to the approved Confluence pages precisely and traceably.",
        "successCriteria": "The affected pages were updated, or there is a clear justification why no change was possible.",
    }

    assert allows_noop_step_completion(
        step,
        "## Step Completion: Confluence Update Assessment\n\nStatus: No Confluence updates performed.\n\nJustification: The existing pages already cover the identified changes sufficiently.",
    )


def test_non_substantive_assistant_response_rejects_hallucinated_tool_markup():
    assert engine_module._is_non_substantive_assistant_response(
        "Ich schaue mir das Projektwissen an.<tool_call>\n<function=get_project_knowledge_overview>\n</function>\n</tool_call>",
        None,
    )


def test_assistant_no_tool_response_signature_normalizes_repeated_summaries():
    first = _assistant_no_tool_response_signature(
        "## Step 3 Complete: Knowledge Map Successfully Updated\n\nI have updated 5 entries from `repo-a`."
    )
    second = _assistant_no_tool_response_signature(
        "## Step 3 Complete: Knowledge Map Successfully Updated\n\nI have updated 7 entries from `repo-b`."
    )

    assert first is not None
    assert first == second


def test_step_completion_summary_detection_and_similarity():
    first = "## Step 1 Complete: Repository Inventory Classification"
    second = "## Step 1 Complete: Repository-Inventar lesen ✅"

    assert _looks_like_step_completion_summary(first)
    assert _looks_like_step_completion_summary(second)
    assert _assistant_no_tool_response_similarity(first, second) >= 0.72
