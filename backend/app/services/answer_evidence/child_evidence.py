"""A child session's evidence, carried up to the parent turn that consolidates it.

A parent consolidates its sub-agents with ``get_context_from_subthreads``. Each accepted subthread
record gets ``evidence_sources``: the openable sources of the child's successful tool calls (the same
structural read as ``evidence.collect_turn_evidence``, over the persisted ``ToolCall`` rows). They sit
in the parent's tool result in the evidence shape, so the parent's turn evidence is the union of its
own tool results and its children's, and the answer evidence guard checks the parent answer against
it. A link no child and no parent tool result carried is still invented.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .evidence import collect_turn_evidence

MAX_CHILD_SOURCES = 20
_SUCCESS = "success"


def child_evidence_sources(tool_calls: Iterable[Any]) -> list[dict[str, str]]:
    """The openable sources of a child session's successful tool calls, bounded, one per citation."""
    history = [
        {"tool_name": getattr(call, "tool_name", ""), "result": getattr(call, "result", None)}
        for call in tool_calls
        if str(getattr(call, "status", "") or "") == _SUCCESS and isinstance(getattr(call, "result", None), dict)
    ]
    evidence = collect_turn_evidence(history)
    return [{"source_url": source.url, "cite_as": source.cite_as} for source in evidence.linkable[:MAX_CHILD_SOURCES]]


__all__ = ["MAX_CHILD_SOURCES", "child_evidence_sources"]
