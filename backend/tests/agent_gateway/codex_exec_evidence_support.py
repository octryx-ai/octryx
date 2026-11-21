"""Shared helpers for the test_codex_exec_evidence_* modules."""

from __future__ import annotations

from app.models import ToolCall

OK_EXCERPT = 'Script completed\nWall time 0.3 seconds\nOutput:\n\n{"chunk_id":"1","exit_code":0,"output":"..."}'


def _counted(rows: list[ToolCall]) -> list[ToolCall]:
    return [row for row in rows if "exec_match" in (row.parameters or {})]
