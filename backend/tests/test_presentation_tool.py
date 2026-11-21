"""S5 — the ``create_presentation`` tool.

The tool is the runtime entry point to the deterministic composer: it reads the
turn's evidence, plans, composes, gates, and returns the artifact. These cases
run asset-free against the python-pptx default template, normalised the same way
an uploaded corporate template is, so the whole path is exercised without the
corporate .potx being in the repository.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.presentation import CreatePresentationTool
from tests.presentation_tool_support import (  # noqa: F401
    _aws_snapshot,
    _context,
    _history_item,
    _run,
    composer_template,
)

# ---------------------------------------------------------------------------
# evidence discipline
# ---------------------------------------------------------------------------


def test_without_snapshot_the_tool_refuses_and_names_the_missing_tool(tmp_path, composer_template):  # noqa: F811
    result = _run(
        CreatePresentationTool(),
        {"topic": "AWS-Architektur", "template_path": str(composer_template)},
        _context(tmp_path, []),
    )

    assert "error" in result
    assert result["required_tool"] == "aws_topology_snapshot"
    # The error must be actionable, not just a refusal.
    assert "aws_topology_snapshot" in result["error"]
    assert result["evidence_sources"] == []
    # Nothing was written: no deck of invented claims exists.
    assert not list(tmp_path.rglob("*.pptx"))


def test_an_externalized_snapshot_is_loaded_from_the_artifact_store(
    tmp_path, composer_template, monkeypatch  # noqa: F811
):
    """Live finding: a 297 KB snapshot is stored as an artifact and the turn
    history keeps only a hard-capped preview (key names, no values). Composing
    from that preview produced a silently thin 3-slide deck with an empty
    account id."""
    from app.tools.presentation_impl import _presentation_evidence

    capped_preview = {
        "_hard_capped": True,
        "_original_type": "dict",
        "keys": ["account_id", "region", "service_summary"],
    }
    # The loop unwraps the storage pointer to its compact preview before a tool
    # sees it: `_artifact_storage` is gone, `artifact_id` stays on the item.
    history = [
        {
            "artifact_id": "art-1",
            "tool_name": "aws_topology_snapshot",
            "tool_call_id": "",
            "params": {},
            "result": capped_preview,
        }
    ]

    assert not _presentation_evidence.snapshot_is_usable(capped_preview)
    assert _presentation_evidence.externalized_snapshot_artifact_id(history) == "art-1"
    # A usable inline snapshot needs no artifact lookup at all.
    assert (
        _presentation_evidence.externalized_snapshot_artifact_id(
            [{"artifact_id": "art-2", "tool_name": "aws_topology_snapshot", "result": _aws_snapshot()}]
        )
        == ""
    )

    async def _load(db, artifact_id):
        assert artifact_id == "art-1"
        return _aws_snapshot()

    monkeypatch.setattr(_presentation_evidence, "load_snapshot_artifact", _load)
    monkeypatch.setattr("app.tools.presentation.load_snapshot_artifact", _load)

    result = _run(
        CreatePresentationTool(),
        {"topic": "AWS-Architektur", "template_path": str(composer_template)},
        _context(tmp_path, history),
    )

    assert "error" not in result
    # The real payload reached the planner: account id and a full deck, not a stub.
    assert result["evidence_sources"][0]["account_id"] == "123456789012"
    assert result["slide_count"] > 3


def test_a_failed_snapshot_result_does_not_count_as_evidence(tmp_path, composer_template):  # noqa: F811
    history = [_history_item("aws_topology_snapshot", {"error": "access denied"})]

    result = _run(
        CreatePresentationTool(),
        {"topic": "AWS-Architektur", "template_path": str(composer_template)},
        _context(tmp_path, history),
    )

    assert result["required_tool"] == "aws_topology_snapshot"


# ---------------------------------------------------------------------------
# the composed deck
# ---------------------------------------------------------------------------


def test_with_snapshot_the_tool_composes_a_gated_deck(tmp_path, composer_template):  # noqa: F811
    history = [_history_item("aws_topology_snapshot", _aws_snapshot())]

    result = _run(
        CreatePresentationTool(),
        {"topic": "AWS-Architektur", "template_path": str(composer_template)},
        _context(tmp_path, history),
    )

    assert "error" not in result
    assert result["status"] == "created"
    assert result["slide_count"] >= 3
    assert len(result["slides"]) == result["slide_count"]
    assert all(slide["title"] for slide in result["slides"])
    # The deck exists on disk and is offered as an artifact.
    deck = Path(result["file_path"])
    assert deck.is_file()
    assert result["artifacts"][0]["path"] == str(deck)
    assert result["artifacts"][0]["media_type"] == "application/vnd.openxmlformats-officedocument"
    # Gate ran; findings are a list (possibly empty) and are reported, never dropped.
    assert isinstance(result["quality_findings"], list)
    assert result["quality_warning_count"] == sum(
        1 for finding in result["quality_findings"] if finding["severity"] == "warning"
    )
    assert "quality" in result["message"] or "warning" in result["message"]
    # The snapshot is named as the evidence source.
    kinds = [source["kind"] for source in result["evidence_sources"]]
    assert "aws_topology_snapshot" in kinds
    assert result["evidence_sources"][0]["account_id"] == "123456789012"


def test_warning_findings_are_surfaced_in_the_result(tmp_path, composer_template, monkeypatch):  # noqa: F811
    """A gate warning must reach the caller — never be silently swallowed."""
    from app.services.office_identity import presentation_composer

    finding = {
        "code": "text_overflow",
        "slide_index": 2,
        "layout_key": "title-and-content",
        "slot_idx": 1,
        "severity": "warning",
        "message": "text exceeds the slot",
    }
    monkeypatch.setattr(presentation_composer, "check_deck_quality", lambda *a, **k: [finding])

    history = [_history_item("aws_topology_snapshot", _aws_snapshot())]
    result = _run(
        CreatePresentationTool(),
        {"topic": "AWS-Architektur", "template_path": str(composer_template)},
        _context(tmp_path, history),
    )

    assert result["quality_findings"] == [finding]
    assert result["quality_warning_count"] == 1
    assert "1 quality warning" in result["message"]


def test_the_same_evidence_produces_the_same_slide_list(tmp_path, composer_template):  # noqa: F811
    history = [_history_item("aws_topology_snapshot", _aws_snapshot())]
    params = {"topic": "AWS-Architektur", "template_path": str(composer_template)}

    first = _run(CreatePresentationTool(), params, _context(tmp_path / "a", history))
    second = _run(CreatePresentationTool(), params, _context(tmp_path / "b", history))

    assert first["slides"] == second["slides"]
    assert first["evidence_sources"] == second["evidence_sources"]
    assert first["quality_findings"] == second["quality_findings"]


def test_max_slides_trims_but_keeps_the_open_points_slide(tmp_path, composer_template):  # noqa: F811
    history = [_history_item("aws_topology_snapshot", _aws_snapshot())]
    params = {"topic": "AWS-Architektur", "template_path": str(composer_template)}

    full = _run(CreatePresentationTool(), params, _context(tmp_path / "full", history))
    trimmed = _run(
        CreatePresentationTool(),
        {**params, "max_slides": 4},
        _context(tmp_path / "trimmed", history),
    )

    assert full["slide_count"] > 4
    assert trimmed["slide_count"] == 4
    # The honesty ledger survives the budget.
    assert trimmed["slides"][-1]["title"] == full["slides"][-1]["title"]
    assert any("max_slides" in warning for warning in trimmed["warnings"])


# ---------------------------------------------------------------------------
# input discipline
# ---------------------------------------------------------------------------


def test_the_composer_is_available_in_diagnosis_mode():
    """Regression: as a change-only tool it was invisible to every diagnosis
    turn, so the documentation workflows it exists for could never call it."""
    from app.tools.definitions import (
        get_tool_definition_metadata,
        is_tool_definition_available_for_agent_type,
    )

    assert is_tool_definition_available_for_agent_type("create_presentation", "diagnosis")
    metadata = get_tool_definition_metadata("create_presentation")
    assert not metadata.change_only
    assert metadata.owner_type == "built_in"
    # The script-executing sibling keeps its stricter classification.
    assert get_tool_definition_metadata("build_presentation_script").change_only


def test_topic_is_required(tmp_path):
    result = _run(CreatePresentationTool(), {}, _context(tmp_path, []))
    assert result["error"] == "topic is required"


def test_an_unusable_template_path_is_named_not_substituted(tmp_path):
    history = [_history_item("aws_topology_snapshot", _aws_snapshot())]

    result = _run(
        CreatePresentationTool(),
        {"topic": "AWS", "template_path": str(tmp_path / "missing.potx")},
        _context(tmp_path, history),
    )

    assert "missing.potx" in result["error"]
