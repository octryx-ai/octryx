"""Short real answers and answers ending with an offer reach the user.

A short answer such as "OK" is not suppressed as a placeholder, and an answer that
explains itself and offers next steps is not suppressed as a transition. The guards stay
for real placeholders and for announcements the run never acts on.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.core.guards.response_guards import (
    build_stalled_step_message,
    is_non_substantive_assistant_response,
    is_transitional_assistant_response,
    looks_like_step_completion_summary,
)
from app.agent.loops.response._loop_response_transition_inputs import TransitionGuardInputs
from app.agent.loops.response._loop_response_transitions import handle_transition_response_guards

LITELLM_TEST_REQUEST = "LiteLLM switch test: reply only with the word OK."
LITELLM_TEST_EXPLANATION = (
    'The LiteLLM test is complete: I replied "OK" as requested. No other task is pending, so I '
    "haven't called any tools.\n\nIf you want to continue, tell me what to look up or change. For "
    "example, I can search Jira, Confluence, or the governed Knowledge base, or inspect AWS or "
    "Kubernetes resources, all read-only. Changes to code or tickets have to go through a workflow run."
)


# --- Placeholder detection is content-based ------------------------------


def test_requested_ok_is_the_answer_not_a_placeholder() -> None:
    assert not is_non_substantive_assistant_response("OK", None, user_message=LITELLM_TEST_REQUEST)


@pytest.mark.parametrize(
    ("reply", "user_message"),
    [
        ("Yes", "Reply with yes or no: is the cluster up?"),
        ("No.", "Answer with yes or no."),
        ("Sure", "Answer only with the word Sure."),
        ("OK", "Reply only with OK, nothing else."),
    ],
)
def test_requested_short_replies_are_answers(reply: str, user_message: str) -> None:
    assert not is_non_substantive_assistant_response(reply, None, user_message=user_message)


@pytest.mark.parametrize("reply", ["42", "Yes", "No", "Bern", "v2"])
def test_short_direct_answers_are_substantive(reply: str) -> None:
    assert not is_non_substantive_assistant_response(reply, None, user_message="What is it?")


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "   ",
        "…",
        "...",
        "⏳",
        "Working on it…",
        "One moment.",
        "Just a moment...",
        "I am working on it.",
        "Tool request knowledge_get: {'key': 'Report Builder'}",
        "<tool_call>",
    ],
)
def test_real_placeholders_stay_placeholders(reply: str) -> None:
    assert is_non_substantive_assistant_response(reply, None, user_message=LITELLM_TEST_REQUEST)


def test_bare_acknowledgement_is_a_placeholder_when_work_was_asked() -> None:
    assert is_non_substantive_assistant_response("OK", None, user_message="Search Jira for open Acme Orders bugs.")
    assert is_non_substantive_assistant_response("Alright.", None, user_message="Check the open tickets.")
    assert is_non_substantive_assistant_response("OK", None)


# --- Offers of next steps are not transitions -----------------------------


def test_complete_answer_ending_with_an_offer_is_not_a_transition() -> None:
    assert not is_transitional_assistant_response(LITELLM_TEST_EXPLANATION, None, True)


@pytest.mark.parametrize(
    "answer",
    [
        "The release was created. If you want, I can search Jira for related tickets.",
        "Done. Let me know if you want me to search Confluence too.",
        "The pod is healthy. I can also check the logs if you'd like.",
        "Done. Tell me if I should check the logs.",
    ],
)
def test_offers_after_an_answer_are_not_transitions(answer: str) -> None:
    assert not is_transitional_assistant_response(answer, None, True)


@pytest.mark.parametrize(
    "announcement",
    [
        "I'll now search Jira for the open tickets.",
        "Let me check the Confluence page.",
        "Now let me look up the AWS security groups.",
        # An offer next to an announcement does not hide the announcement.
        "Let me check Jira. If you want, I can also check Confluence.",
        "I will check the logs now. Feel free to ask for the tickets afterwards.",
    ],
)
def test_announcements_without_action_are_still_transitions(announcement: str) -> None:
    assert is_transitional_assistant_response(announcement, None, True)


# --- Loop level: the reply reaches the user, no nudge ---------------------


async def _noop(**kwargs: Any) -> None:
    return None


class _DummyDB:
    async def commit(self) -> None:
        return None


async def _run_guard(content: str, user_message: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    return await handle_transition_response_guards(TransitionGuardInputs(
        db=_DummyDB(),
        session_id="session-litellm-test",
        runtime={"provider_name": "litellm"},
        response={"usage": {}},
        request_messages=[{"role": "user", "content": user_message}],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 2},
        usage_model="litellm-model",
        content=content,
        tool_calls=None,
        current_tool_definitions=[{"name": "search_jira_tickets"}, {"name": "knowledge_search"}],
        current_step=None,
        has_followup_steps=False,
        turn_tool_history=[],
        consecutive_non_progress_response_count=0,
        consecutive_transitional_response_count=0,
        is_transitional_assistant_response=is_transitional_assistant_response,
        is_non_substantive_assistant_response=is_non_substantive_assistant_response,
        looks_like_step_completion_summary=looks_like_step_completion_summary,
        build_stalled_step_message=build_stalled_step_message,
        persist_suppressed_runtime_response=_noop,
        persist_turn_trace=_noop,
        persist_traced_assistant_message=_noop,
        workflow_id="",
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["OK", LITELLM_TEST_EXPLANATION])
async def test_loop_returns_the_litellm_test_replies_without_a_nudge(content: str) -> None:
    messages: list[dict[str, str]] = []

    outcome = await _run_guard(content, LITELLM_TEST_REQUEST, messages)

    assert outcome["action"] == "none"
    assert outcome["consecutive_non_progress_response_count"] == 0
    assert outcome["consecutive_transitional_response_count"] == 0
    assert messages == []


@pytest.mark.asyncio
async def test_loop_still_nudges_a_bare_ok_when_work_was_asked() -> None:
    messages: list[dict[str, str]] = []

    outcome = await _run_guard("OK", "Search Jira for open Acme Orders bugs.", messages)

    assert outcome["action"] == "continue"
    assert outcome["consecutive_non_progress_response_count"] == 1
    assert [message["role"] for message in messages] == ["assistant", "system"]


@pytest.mark.asyncio
async def test_loop_still_nudges_an_announcement_without_action() -> None:
    messages: list[dict[str, str]] = []

    outcome = await _run_guard("I'll now search Jira for the open tickets.", "Find open Acme Orders bugs.", messages)

    assert outcome["action"] == "continue"
    assert outcome["consecutive_transitional_response_count"] == 1
    assert [message["role"] for message in messages] == ["assistant", "system"]
