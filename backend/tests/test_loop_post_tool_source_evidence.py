"""Source evidence answers: final answer sanitizing and no person identity source fallbacks after tool calls."""

import pytest

from app.agent.loops.outcome._loop_post_tool import handle_post_tool_outcome
from app.agent.loops.outcome._loop_post_tool_inputs import PostToolInputs
from app.agent.loops.response._loop_source_evidence_answer import _sanitize_source_evidence_final_answer
from tests.loop_post_tool_support import _build_kwargs, _noop_async


def test_source_evidence_final_answer_sanitizer_removes_redacted_email_line() -> None:
    content = (
        "### Alice Example\n\n"
        "- **Jira Username**: `alice`\n"
        "- **Email contact**: Redacted for privacy.\n"
        "- **Status**: Active.\n\n"
        "Evidence continues."
    )

    sanitized = _sanitize_source_evidence_final_answer(content)

    assert "Email" not in sanitized
    assert "Redacted" not in sanitized
    assert "Jira Username" in sanitized
    assert "Evidence continues." in sanitized


def test_source_evidence_final_answer_sanitizer_rewrites_knowledge_authorship_inference() -> None:
    content = (
        "## Missing or unchecked coverage\n\n"
        "- No Knowledge Base articles authored by him were found in the search result.\n"
        "- **Knowledge base authorship**: No direct entries matched his name.\n"
        "- Formal role title was not retrieved."
    )

    sanitized = _sanitize_source_evidence_final_answer(content)

    assert "authored by him" not in sanitized
    assert "Knowledge base authorship" not in sanitized
    assert "No direct Knowledge entries matched the resolved name/alias search" in sanitized
    assert "Formal role title" in sanitized


def test_source_evidence_final_answer_sanitizer_inserts_missing_knowledge_user_activity() -> None:
    content = (
        "## Confirmed evidence\n\n"
        "- **Jira user**: Alice Example is active.\n"
        "- **Confluence**: Creator/contributor of at least 2 pages.\n\n"
        "## Reasoned interpretation\n\n"
        "He appears to work on Acme Orders."
    )
    request_messages = [
        {
            "role": "system",
            "content": (
                "[source_evidence_final_answer]\n"
                "Evidence summary:\n"
                "Knowledge-base user evidence: `source_people` found 671 Knowledge entries.\n"
                "- Sources: confluence: 404, jira: 230, bitbucket: 37.\n"
            ),
        }
    ]

    sanitized = _sanitize_source_evidence_final_answer(content, request_messages=request_messages)

    assert "- **Knowledge Base activity**" in sanitized
    assert "671 Knowledge entries" in sanitized
    assert "confluence: 404, jira: 230, bitbucket: 37" in sanitized
    assert "**Live Confluence check**" in sanitized
    assert "at least one" not in sanitized
    assert sanitized.index("Knowledge Base activity") < sanitized.index("Jira user")


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_does_not_force_person_identity_source_tool_fallback() -> None:
    kwargs = _build_kwargs(
        wrapup_forced=False,
        persist_traced_assistant_message=_noop_async,
        current_user_message="Who is Alice Example?",
        current_step={},
        active_steps=[],
        workflow_contract={
            "workflow_id": "source_evidence_lookup",
            "source_strategy": "person_identity",
            "source_topic": "Alice Example",
            "source_aliases": ["alice"],
            "tool_selection_mode": "llm_selected",
            "allowed_tools": ["search_jira_tickets", "knowledge_search", "search_confluence"],
        },
        turn_tool_history=[
            {
                "tool_name": "search_jira_users",
                "result": {"users": [{"display_name": "Alice Example", "name": "alice"}], "total": 1},
            },
            {"tool_name": "search_jira_tickets", "result": {"total": 0, "results": []}},
        ],
        tool_results=[
            {
                "tool_name": "knowledge_search",
                "result": {"total": 0, "results": []},
            }
        ],
    )
    kwargs["current_allowed_tool_names"] = {"search_jira_tickets", "knowledge_search", "search_confluence"}
    kwargs["executed_tool_names"] = {"search_jira_users", "search_jira_tickets", "knowledge_search"}

    result = await handle_post_tool_outcome(PostToolInputs(**kwargs))

    assert result["action"] == "append_system_message"
    assert "forced_tool_calls" not in result
    assert "[source_evidence_final_answer]" not in result["system_message"]


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_does_not_synthesize_person_identity_source_fallback() -> None:
    synthesized: list[dict[str, object]] = []

    async def _capture_synthesized_message(**kwargs):  # type: ignore[no-untyped-def]
        synthesized.append(kwargs)
        return None

    kwargs = _build_kwargs(
        wrapup_forced=False,
        persist_traced_assistant_message=_noop_async,
        persist_synthesized_tool_assistant=_capture_synthesized_message,
        current_user_message="Who is Alice Example?",
        current_step={},
        active_steps=[],
        workflow_contract={
            "workflow_id": "source_evidence_lookup",
            "source_strategy": "person_identity",
            "source_topic": "Alice Example",
            "source_aliases": ["alice"],
            "tool_selection_mode": "llm_selected",
            "allowed_tools": ["search_jira_tickets", "knowledge_search", "search_confluence"],
        },
        turn_tool_history=[
            {
                "tool_name": "search_jira_users",
                "result": {
                    "project_key": "ACME",
                    "users": [
                        {
                            "display_name": "Alice Example",
                            "name": "alice",
                            "key": "JIRAUSER17330",
                            "email": "alice@example.com",
                        }
                    ],
                    "total": 1,
                },
            },
            {"tool_name": "search_jira_tickets", "result": {"total": 0, "results": []}},
            {"tool_name": "knowledge_search", "result": {"total": 0, "results": []}},
        ],
        tool_results=[
            {
                "tool_name": "search_confluence",
                "result": {"total": 0, "results": []},
            }
        ],
    )
    kwargs["current_allowed_tool_names"] = {"search_jira_tickets", "knowledge_search", "search_confluence"}
    kwargs["executed_tool_names"] = {"search_jira_users", "search_jira_tickets", "knowledge_search", "search_confluence"}

    result = await handle_post_tool_outcome(PostToolInputs(**kwargs))

    assert result["action"] == "append_system_message"
    assert "[source_evidence_final_answer]" not in result["system_message"]
    assert synthesized == []
