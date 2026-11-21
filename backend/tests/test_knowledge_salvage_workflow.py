"""Tests for the knowledge-evidence salvage synthesis and the transition-stall fallback answer."""

from __future__ import annotations

from app.agent.loops.response._loop_response_transition_stalls import _knowledge_fallback_answer
from app.services.knowledge_salvage import KNOWLEDGE_TOOL_NAMES, build_knowledge_salvage_answer


def _knowledge_tool_history() -> list[dict[str, object]]:
    return [
        {
            # The governed ledger search: cited passages, each with its cite_as source link.
            "tool_name": "knowledge_search",
            "result": {
                "state": "ok",
                "result_count": 2,
                "evidence": [
                    {
                        "source_title": "Report Builder Startup",
                        "section": None,
                        "text": "Startup documentation covers init behavior and runtime prerequisites.",
                        "cite_as": "[Report Builder Startup](https://docs.example.local/report-builder-startup)",
                    },
                    {
                        "source_title": "Report Builder Maintenance",
                        "section": "Export checks",
                        "text": "Maintenance notes explain release operations and export checks.",
                        "cite_as": (
                            "[Report Builder Maintenance § Export checks]"
                            "(https://docs.example.local/report-builder-maint)"
                        ),
                    },
                ],
            },
        },
    ]


def test_english_synthesis_from_knowledge_tool_history() -> None:
    answer = build_knowledge_salvage_answer(
        "What can you tell me about Report Builder?",
        _knowledge_tool_history(),
    )

    assert answer.startswith("I found 2 matching Knowledge entries")
    assert "- Report Builder Startup: Startup documentation covers init behavior" in answer
    assert "- Report Builder Maintenance § Export checks: Maintenance notes explain" in answer
    assert "Sources: " in answer
    assert "[Report Builder Startup](https://docs.example.local/report-builder-startup)" in answer


def test_empty_answer_when_no_knowledge_tool_ran() -> None:
    history = [
        {"tool_name": "search_jira_tickets", "result": {"total": 3, "results": []}},
        {"tool_name": "web_search", "result": {"results": [{"title": "x", "snippet": "y"}]}},
    ]

    assert build_knowledge_salvage_answer("What about Report Builder?", history) == ""
    assert build_knowledge_salvage_answer("What about Report Builder?", []) == ""
    assert not any(str(item.get("tool_name")) in KNOWLEDGE_TOOL_NAMES for item in history)


def test_transition_fallback_is_the_direct_salvage() -> None:
    tool_history = _knowledge_tool_history()
    user_message = "What can you tell me about Report Builder?"

    fallback = _knowledge_fallback_answer(user_message=user_message, turn_tool_history=tool_history)
    direct = build_knowledge_salvage_answer(user_message, tool_history, max_items=10, content_chars=420)

    assert fallback == direct
    assert fallback.startswith("I found 2 matching Knowledge entries")


def test_an_empty_governed_search_is_answered_as_nothing_documented() -> None:
    """No hits in the ledger is the answer; there is no handover to another store."""
    history = [{"tool_name": "knowledge_search", "result": {"state": "ok", "result_count": 0, "evidence": []}}]

    answer = _knowledge_fallback_answer(
        user_message="What can you tell me about Report Builder?", turn_tool_history=history
    )

    assert answer == "I searched the Workspace Knowledge, but found nothing documented about this."
