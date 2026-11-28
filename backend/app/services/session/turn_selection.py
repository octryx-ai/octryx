"""The explicit selection a turn records on its session, the same on both entry paths."""

from __future__ import annotations

from typing import Any

from ..workflow_contracts.decisions import record_workflow_decisions


def record_turn_selection(
    metadata: dict[str, Any], *, workflow_key: str, workflow_decisions: dict[str, str] | None
) -> None:
    metadata["workflow_key"] = workflow_key
    record_workflow_decisions(metadata, workflow_decisions)


__all__ = ["record_turn_selection"]
