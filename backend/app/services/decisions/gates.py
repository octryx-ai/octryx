"""Turn gates as decision records (O2): the execution gate and the runtime-readiness gate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from .recorder import (
    GATE_EXECUTION,
    GATE_RUNTIME_READINESS,
    OUTCOME_DENIED,
    OUTCOME_NEEDS_APPROVAL,
    OUTCOME_NEEDS_CLARIFICATION,
    OUTCOME_NEEDS_CONFIGURATION,
    record_gate_decision,
)

TURN_ACTION = "run_turn"
_GATES = {"execution_gate": GATE_EXECUTION, "runtime_readiness": GATE_RUNTIME_READINESS}
_OUTCOMES = {
    "needs_approval": OUTCOME_NEEDS_APPROVAL,
    "needs_clarification": OUTCOME_NEEDS_CLARIFICATION,
    "needs_configuration": OUTCOME_NEEDS_CONFIGURATION,
}
# A workflow proposal waiting for confirmation is an approval; the approval row records it.
_RECORDED_BY_APPROVAL = {"needs_confirmation"}


async def record_gate_outcome(db: AsyncSession, *, session_id: str, run_key: str, raw_output: Any) -> None:
    marker = raw_output.get("gate_outcome") if isinstance(raw_output, Mapping) else None
    if not isinstance(marker, Mapping) or not str(marker.get("gate") or "").strip():
        return
    status = str(marker.get("status") or "").strip()
    if status in _RECORDED_BY_APPROVAL:
        return
    session = await db.get(Session, session_id)
    gate = str(marker.get("gate")).strip()
    record_gate_decision(
        gate=_GATES.get(gate, gate),
        outcome=_OUTCOMES.get(status, OUTCOME_DENIED),
        action=TURN_ACTION,
        resource=str(marker.get("label") or gate),
        principal=session.user_id if session is not None else "",
        workspace_id=session.project_id if session is not None else None,
        session_id=session_id,
        run_key=run_key,
        rule=f"{gate}: {status}" if status else gate,
        reason=str(marker.get("reason") or ""),
    )


