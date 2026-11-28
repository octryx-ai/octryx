"""Explicit gate outcomes in canonical traces. Trace persistence reads only the ``gate_outcome`` entry, never a
provider-name string."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

GATE_OUTCOME_KEY = "gate_outcome"
TRACE_RUN_STATUS_BLOCKED = "blocked"
TRACE_SPAN_TYPE_GATE = "gate"
_GATE_TEXT_MAX_CHARS = 300


def gate_outcome_marker(*, gate: str, label: str, status: str, reason: str) -> dict[str, Any]:
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
    status: str
    span_type: str
    span_suffix: str
    name: str
    gate_outcome: dict[str, Any] | None = None


def resolve_trace_root_shape(output_payload: Mapping[str, Any]) -> TraceRootShape:
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
