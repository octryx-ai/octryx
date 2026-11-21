"""Explicit gate outcomes in canonical traces.

A turn blocked by the execution gate or the runtime-readiness gate never reaches a
model. The gate that blocks it adds an explicit ``gate_outcome`` entry to the
persisted raw output. Trace persistence reads only that entry, never a provider-name
string, and records the run as ``blocked`` with a ``gate`` root span. It does not
record a successful ``llm`` span named "agent turn".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

GATE_OUTCOME_KEY = "gate_outcome"
TRACE_RUN_STATUS_BLOCKED = "blocked"
TRACE_SPAN_TYPE_GATE = "gate"
_GATE_TEXT_MAX_CHARS = 300


def gate_outcome_marker(*, gate: str, label: str, status: str, reason: str) -> dict[str, Any]:
    """Return the raw-output entry a gate adds when it blocks a turn before any model call."""
    return {
        GATE_OUTCOME_KEY: {
            "gate": str(gate or "").strip(),
            "label": str(label or "").strip()[:_GATE_TEXT_MAX_CHARS],
            "status": str(status or "").strip(),
            "reason": str(reason or "").strip()[:_GATE_TEXT_MAX_CHARS],
        }
    }


@dataclass(frozen=True, slots=True)
class TraceRootShape:
    """How the canonical trace records the turn's root span and run status."""

    status: str
    span_type: str
    span_suffix: str
    name: str
    gate_outcome: dict[str, Any] | None = None


def resolve_trace_root_shape(output_payload: Mapping[str, Any]) -> TraceRootShape:
    """Return the root span shape for a persisted turn outcome.

    An explicit gate marker makes the run ``blocked`` with a ``gate`` span. Otherwise the
    turn was a model turn: ``error`` when the output carries an error, else ``success``.
    """
    outcome = output_payload.get(GATE_OUTCOME_KEY)
    gate = str(outcome.get("gate") or "").strip() if isinstance(outcome, Mapping) else ""
    if gate:
        label = str(outcome.get("label") or "").strip() or f"{gate} gate"
        return TraceRootShape(
            status=TRACE_RUN_STATUS_BLOCKED,
            span_type=TRACE_SPAN_TYPE_GATE,
            span_suffix=TRACE_SPAN_TYPE_GATE,
            name=label,
            gate_outcome={
                "gate": gate,
                "label": label,
                "status": str(outcome.get("status") or "").strip(),
                "reason": str(outcome.get("reason") or "").strip()[:_GATE_TEXT_MAX_CHARS],
            },
        )
    status = "error" if output_payload.get("error") else "success"
    return TraceRootShape(status=status, span_type="llm", span_suffix="llm", name="agent turn")


__all__ = [
    "GATE_OUTCOME_KEY",
    "TRACE_RUN_STATUS_BLOCKED",
    "TRACE_SPAN_TYPE_GATE",
    "TraceRootShape",
    "gate_outcome_marker",
    "resolve_trace_root_shape",
]
