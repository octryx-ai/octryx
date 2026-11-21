"""Mermaid-fence reminder: literal signal, one nudge per turn, never a loop."""

from __future__ import annotations

from app.agent.loops.response._loop_mermaid_reminder import detect_mermaid_instead_of_artifact

_MERMAID_ANSWER = "Hier ist das Diagramm:\n```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n"


def test_mermaid_fence_without_artifact_triggers_reminder() -> None:
    snapshot: dict = {}
    event = detect_mermaid_instead_of_artifact(
        assistant_content=_MERMAID_ANSWER,
        turn_tool_history=[],
        context_snapshot=snapshot,
    )
    assert event is not None
    assert event["rule"] == "mermaid_instead_of_diagram_artifact"
    assert "select_workflow" in event["message"]
    assert "'diagram'" in event["message"]
    assert snapshot["mermaid_artifact_reminder_fired"] is True


def test_reminder_fires_at_most_once_per_turn() -> None:
    snapshot: dict = {}
    first = detect_mermaid_instead_of_artifact(
        assistant_content=_MERMAID_ANSWER, turn_tool_history=[], context_snapshot=snapshot
    )
    second = detect_mermaid_instead_of_artifact(
        assistant_content=_MERMAID_ANSWER, turn_tool_history=[], context_snapshot=snapshot
    )
    assert first is not None
    assert second is None


def test_plain_text_and_existing_artifacts_pass_untouched() -> None:
    assert (
        detect_mermaid_instead_of_artifact(
            assistant_content="Der OAuth-Flow funktioniert so: ...",
            turn_tool_history=[],
            context_snapshot={},
        )
        is None
    )
    history = [{"tool_name": "create_diagram", "result": {"status": "created", "diagram_id": "d1"}}]
    assert (
        detect_mermaid_instead_of_artifact(
            assistant_content=_MERMAID_ANSWER,
            turn_tool_history=history,
            context_snapshot={},
        )
        is None
    )
