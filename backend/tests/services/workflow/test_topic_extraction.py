"""A request's topic is a parameter that names something, never a stray article or a save path."""

import pytest

from app.services.workflow_contracts.topic import infer_topic


@pytest.mark.parametrize(
    ("prompt", "topic"),
    [
        (
            "Create a presentation about the benefits and risks of LLM agents and save it as decks/llm-agents.pptx.",
            "benefits and risks of LLM agents",
        ),
        (
            "Write a research report on container orchestration history and save it as reports/orchestration.docx.",
            "container orchestration history",
        ),
        ("Create an activity diagram for the loan approval process.", "loan approval process"),
        ("Write a report about LightRAG and create a presentation.", "LightRAG"),
        (
            "Create a cited Word research report about ticketing API integration benefits, risks, use cases, "
            "and adoption.",
            "ticketing API integration",
        ),
        (
            "Research ticketing API integration and create a concise cited Word report covering benefits, risks, "
            "use cases, and enterprise rollout guidance.",
            "ticketing API integration",
        ),
        ("Run deep research on ticketing API integration and create a cited Word report.", "ticketing API integration"),
        (
            "Erstelle im output-Ordner ein Word Dokument als Deep Research zu "
            "'LLM im Unternehmen: Vorteile, Nachteile und Einsatz' mit IEEE Zitaten.",
            "LLM im Unternehmen: Vorteile, Nachteile und Einsatz",
        ),
    ],
)
def test_the_topic_names_the_subject_without_save_instructions(prompt, topic):
    assert infer_topic(prompt) == topic


def test_a_capture_that_names_nothing_falls_back_to_the_request_not_a_word():
    prompt = "Research the history of container orchestration using only web pages, no citations needed."
    topic = infer_topic(prompt)
    assert "container orchestration" in topic
    assert topic not in {"the", "knowledge"}


def test_a_request_without_content_keeps_the_explicit_default():
    assert infer_topic("Create a presentation.") == "knowledge"
