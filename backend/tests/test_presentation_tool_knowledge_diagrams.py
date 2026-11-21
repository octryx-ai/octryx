"""Knowledge search results become sourced facts that reach the deck, and the turn's diagrams are rendered and embedded or reported when they cannot be rendered."""

from __future__ import annotations

from app.tools.presentation import CreatePresentationTool
from app.tools.presentation_impl._presentation_evidence import knowledge_facts_from_history
from tests.presentation_tool_support import (  # noqa: F401
    _aws_snapshot,
    _context,
    _history_item,
    _run,
    composer_template,
)

# ---------------------------------------------------------------------------
# optional evidence
# ---------------------------------------------------------------------------


def test_knowledge_search_results_become_sourced_facts():
    history = [
        _history_item(
            "knowledge_search",
            {
                "state": "ok",
                "evidence": [
                    {"text": "Die Plattform läuft auf EKS", "cite_as": "[Runtime](https://docs.example/runtime)"},
                    {"text": "RDS PostgreSQL Multi-AZ", "cite_as": "[Daten](https://docs.example/data)"},
                ],
            },
        )
    ]

    facts = knowledge_facts_from_history(history)

    assert facts == [
        {"statement": "Die Plattform läuft auf EKS", "source": "[Runtime](https://docs.example/runtime)"},
        {"statement": "RDS PostgreSQL Multi-AZ", "source": "[Daten](https://docs.example/data)"},
    ]


def test_a_knowledge_entry_without_a_traceable_source_is_dropped():
    """No source, no claim — the planner then marks the gap instead."""
    history = [
        _history_item("knowledge_search", {"state": "ok", "evidence": [{"text": "Behauptung ohne Quelle"}]}),
    ]

    assert knowledge_facts_from_history(history) == []


def test_knowledge_facts_reach_the_deck(tmp_path, composer_template):  # noqa: F811
    history = [
        _history_item("aws_topology_snapshot", _aws_snapshot()),
        _history_item(
            "knowledge_search",
            {
                "state": "ok",
                "evidence": [
                    {"text": "Die Plattform läuft auf EKS", "cite_as": "[Runtime](https://docs.example/runtime)"}
                ],
            },
        ),
    ]

    result = _run(
        CreatePresentationTool(),
        {"topic": "AWS-Architektur", "template_path": str(composer_template)},
        _context(tmp_path, history),
    )

    knowledge_source = next(
        source for source in result["evidence_sources"] if source["kind"] == "knowledge_search"
    )
    assert knowledge_source["keys"] == ["[Runtime](https://docs.example/runtime)"]


def test_diagrams_from_the_turn_are_rendered_and_embedded(tmp_path, composer_template, monkeypatch):  # noqa: F811
    """Diagram images come from our own pipeline, rendered via the export service."""
    import io

    from PIL import Image

    from app.tools.presentation_impl import _presentation_evidence

    buffer = io.BytesIO()
    Image.new("RGB", (800, 550), "white").save(buffer, format="PNG")
    png_bytes = buffer.getvalue()
    monkeypatch.setattr(
        "app.services.diagram_export_service.render_diagram_png",
        lambda **kwargs: png_bytes,
    )
    assert _presentation_evidence.DIAGRAM_TOOL_NAMES  # the module under test is wired

    history = [
        _history_item("aws_topology_snapshot", _aws_snapshot()),
        _history_item(
            "create_diagram",
            {
                "diagram_id": "aws-overview-1234",
                "diagram_xml": "<mxGraphModel><root/></mxGraphModel>",
                "title": "AWS Topologie — Überblick",
            },
        ),
    ]

    result = _run(
        CreatePresentationTool(),
        {"topic": "AWS-Architektur", "template_path": str(composer_template)},
        _context(tmp_path, history),
    )

    diagram_source = next(source for source in result["evidence_sources"] if source["kind"] == "diagram")
    assert diagram_source["diagram_ids"] == ["aws-overview-1234"]
    assert any(slide["title"] == "AWS Topologie — Überblick" for slide in result["slides"])


def test_an_unrenderable_diagram_is_reported_not_faked(tmp_path, composer_template, monkeypatch):  # noqa: F811
    from app.services.diagram_export_service import DiagramRendererUnavailableError

    def _unavailable(**kwargs):
        raise DiagramRendererUnavailableError("renderer_unavailable: drawio CLI not found")

    monkeypatch.setattr("app.services.diagram_export_service.render_diagram_png", _unavailable)

    history = [
        _history_item("aws_topology_snapshot", _aws_snapshot()),
        _history_item(
            "create_diagram",
            {"diagram_id": "d1", "diagram_xml": "<mxGraphModel><root/></mxGraphModel>", "title": "T"},
        ),
    ]

    result = _run(
        CreatePresentationTool(),
        {"topic": "AWS-Architektur", "template_path": str(composer_template)},
        _context(tmp_path, history),
    )

    assert any("renderer_unavailable" in warning for warning in result["warnings"])
    assert all(source["kind"] != "diagram" for source in result["evidence_sources"])
