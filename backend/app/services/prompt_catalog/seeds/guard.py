"""Seeds of the loop control guards: step contracts, evidence completion, stuck-loop recovery."""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "guard"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="guard.research.no_sources_stop",
        area=AREA,
        title="Stop: research step kept finding no usable sources",
        seed=(
            "the research-evidence step kept finding no usable sources for the requested document topic. Broaden the "
            "topic or provide concrete source hints before retrying."
        ),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
)
