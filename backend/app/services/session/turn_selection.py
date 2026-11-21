"""The explicit selection a turn records on its session, the same on both entry paths.

:func:`record_turn_selection` records the workflow key the client sent (mirrored for
cross-device restore; bootstrap exposes it as ``selectedSession.workflowKey``) and the
workflow decisions of the turn. Turn preparation calls it for both entry paths
(``turn_session_record``), always after ``begin_chat_turn``.
"""

from __future__ import annotations

from typing import Any

from ..workflow_contracts.decisions import record_workflow_decisions


def record_turn_selection(
    metadata: dict[str, Any], *, workflow_key: str, workflow_decisions: dict[str, str] | None
) -> None:
    metadata["workflow_key"] = workflow_key
    record_workflow_decisions(metadata, workflow_decisions)


__all__ = ["record_turn_selection"]
