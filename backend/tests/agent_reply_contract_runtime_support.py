"""Shared helpers for the test_agent_reply_contract_runtime_* modules."""

from __future__ import annotations

from sqlalchemy import select

from app.models import TurnTrace
from app.services.session.turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY
from app.services.session.turn_execution_summary import build_turn_execution_summary
from app.services.session.turn_execution_summary_service import load_turn_execution_evidence
from tests.agent_tool_surface_runtime_support import _agent

CONTRACT = {
    "kind": "json_object",
    "schema": {
        "type": "object",
        "properties": {"total": {"type": "integer"}, "items": {"type": "array", "items": {"type": "integer"}}},
        "required": ["total"],
    },
}


VALID = '{"total": 43, "items": [31, 8, 4]}'


FENCED = '```json\n{"total": 43}\n```'


def _checked_agent(contract=CONTRACT) -> dict:
    return {**_agent(None), "replyContract": contract}


async def _final_trace(db, session_id: str) -> TurnTrace:
    rows = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id))).scalars().all()
    return max(rows, key=lambda row: row.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY]["turn"]["sequence"])


async def _summary(db, trace: TurnTrace) -> dict:
    return build_turn_execution_summary(await load_turn_execution_evidence(db, trace))
