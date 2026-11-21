"""Shared helpers for the test_connector_evidence_fields_* modules."""

from __future__ import annotations

from types import SimpleNamespace

JIRA = "https://jira.example.test"


def _context(**config) -> SimpleNamespace:
    return SimpleNamespace(
        project_config=config,
        turn_context_snapshot=None,
        current_user_message="",
        project_ids=[],
        user_id="u1",
        db=None,
    )


def _issue(key: str, summary: str) -> dict:
    return {"key": key, "fields": {"summary": summary, "status": {"name": "Open"}, "priority": {"name": "High"}}}


def _assert_source(item: dict, url: str, *, title: str | None = None) -> None:
    assert item["source_url"] == url
    assert item["cite_as"].endswith(f"]({url})")
    if title is not None:
        assert item["source_title"] == title
