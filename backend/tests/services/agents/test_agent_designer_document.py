"""Designer document <-> Agent Definition translation: round trip and explicit refusals."""

from __future__ import annotations

import pytest

from app.services.agent_designer.document import definition_from_document, document_from_definition
from app.services.agent_designer.document_model import DesignerDocumentError

STEPS = [
    {"id": "step-a", "name": "Research", "instructions": "Find sources.", "step_config": {"keep": 1}},
    {
        "id": "step-b",
        "name": "Write",
        "instructions": "Write the answer.",
        "step_config": {"designer": {"node_type": "AgentNode", "coordinates": {"x": 5, "y": 6}, "max_iterations": 3}},
    },
]


def _document() -> dict:
    return document_from_definition(name="Analyst", description="Two steps", steps=STEPS)


def _issue_codes(document: dict) -> list[str]:
    with pytest.raises(DesignerDocumentError) as caught:
        definition_from_document(document)
    return [issue.code for issue in caught.value.issues]


def test_round_trip_keeps_order_text_and_designer_settings() -> None:
    designed = definition_from_document(_document())

    assert (designed.name, designed.description) == ("Analyst", "Two steps")
    assert [(step.step_id, step.name, step.instructions) for step in designed.steps] == [
        ("step-a", "Research", "Find sources."),
        ("step-b", "Write", "Write the answer."),
    ]
    assert designed.steps[1].designer_config == {
        "max_iterations": 3,
        "node_type": "AgentNode",
        "coordinates": {"x": 5.0, "y": 6.0},
    }


def _as_designer_exports(document: dict) -> dict:
    for node in document["definition"]["nodes"]:
        node["title"] = node["config"].get("title") or {"SingleLLMCallNode": "Single LLM Call"}.get(
            node["node_type"], node["id"]
        )
    return document


def test_titles_survive_the_designer_export() -> None:
    designed = definition_from_document(_as_designer_exports(_document()))
    assert [step.name for step in designed.steps] == ["Research", "Write"]


def test_the_designer_edit_order_follows_the_links_not_the_node_list() -> None:
    document = _document()
    nodes = document["definition"]["nodes"]
    nodes.reverse()
    document["definition"]["links"] = [
        {"source_id": "octryx-input", "target_id": "step-b"},
        {"source_id": "step-b", "target_id": "step-a"},
        {"source_id": "step-a", "target_id": "octryx-output"},
    ]
    assert [step.step_id for step in definition_from_document(document).steps] == ["step-b", "step-a"]


def test_node_types_without_an_agent_definition_meaning_are_refused_not_dropped() -> None:
    document = _document()
    document["definition"]["nodes"].append({"id": "code", "title": "Code", "node_type": "PythonFuncNode", "config": {}})
    with pytest.raises(DesignerDocumentError) as caught:
        definition_from_document(document)
    assert caught.value.issues[0].as_dict() == {"code": "unsupported_node_type", "node_ids": ["code"]}


def test_a_branching_graph_is_refused() -> None:
    document = _document()
    document["definition"]["links"].append({"source_id": "octryx-input", "target_id": "step-b"})
    assert _issue_codes(document) == ["graph_not_linear"]


def test_a_disconnected_step_is_refused() -> None:
    document = _document()
    document["definition"]["links"] = [{"source_id": "octryx-input", "target_id": "octryx-output"}]
    assert _issue_codes(document) == ["graph_not_linear"]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d["definition"]["nodes"].pop(), "needs_one_input_and_one_output"),
        (lambda d: d["definition"]["nodes"][1].update(title="  "), "step_title_required"),
        (lambda d: d.update(definition="nodes"), "malformed_document"),
    ],
)
def test_structural_defects_are_named(mutate, code) -> None:
    document = _document()
    mutate(document)
    assert code in _issue_codes(document)
