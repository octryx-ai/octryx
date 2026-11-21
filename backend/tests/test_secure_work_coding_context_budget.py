from __future__ import annotations

from app.services.secure_work.coding.coding_context_budget import (
    budget_fragment_content,
    build_coding_context_budget_snapshot,
    coding_context_budget_metadata,
)


def test_coding_context_budget_caps_fragments_and_marks_truncation():
    snapshot = build_coding_context_budget_snapshot(
        {"description": "x" * 5000, "operator_request": "short"},
        fragment_char_caps={"description": 100},
    )

    description = snapshot["fragments"]["description"]
    assert description["truncated"] is True
    assert description["prompt_chars"] <= 100
    assert budget_fragment_content(snapshot, "description").endswith("[... truncated by coding context budget ...]")
    assert snapshot["fragments"]["operator_request"]["truncated"] is False


def test_coding_context_budget_metadata_does_not_persist_fragment_content():
    snapshot = build_coding_context_budget_snapshot({"description": "secret-like local content"})

    metadata = coding_context_budget_metadata(snapshot)

    assert metadata["description"]["original_chars"] == len("secret-like local content")
    assert "content" not in metadata["description"]


def test_coding_context_budget_does_not_mark_whitespace_trim_as_truncation():
    snapshot = build_coding_context_budget_snapshot({"description": "  compact evidence  "})

    assert budget_fragment_content(snapshot, "description") == "compact evidence"
    assert snapshot["fragments"]["description"]["truncated"] is False
