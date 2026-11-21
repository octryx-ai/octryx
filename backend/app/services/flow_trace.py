from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FlowNodeRun
from ..models.agent.orchestrator_agent import OrchestratorAgentRun
from .flow_orchestration.decision_trace import decision_trace_from_refs
from .flow_orchestration.planning import flow_run_plan_state
from .flow_orchestration.recovery import flow_run_lease_state, flow_run_progress_state
from .flow_orchestration.validation_loop import validation_loop_state
from .runtime_acceptance import runtime_acceptance_state
from .runtime_failure_taxonomy import runtime_failure_state

SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|authorization|bearer|client[_-]?secret|credential|password|private[_-]?key|refresh[_-]?token|secret|token)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERN = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/=-]+|(?:api[_-]?key|password|secret|token)\s*[:=]\s*['\"]?[^'\"\s,}]+)",
    re.IGNORECASE,
)
MAX_STRING_LENGTH = 1600
MAX_LIST_ITEMS = 50
MAX_DICT_ITEMS = 80
REDACTED = "[redacted]"


async def get_flow_run_trace(db: AsyncSession, *, run_id: str) -> dict[str, Any]:
    run = await db.get(OrchestratorAgentRun, run_id)
    if run is None or not run.flow_definition_version_id:
        raise HTTPException(status_code=404, detail="Flow run not found")
    node_runs = await list_flow_node_runs(db, run_id=run.id)
    return {
        "run": serialize_flow_run(run),
        "node_runs": [serialize_flow_node_run(node_run) for node_run in node_runs],
    }


async def get_flow_node_run_trace(db: AsyncSession, *, run_id: str, node_run_id: str) -> dict[str, Any]:
    run = await db.get(OrchestratorAgentRun, run_id)
    if run is None or not run.flow_definition_version_id:
        raise HTTPException(status_code=404, detail="Flow run not found")
    node_run = await db.get(FlowNodeRun, node_run_id)
    if node_run is None or node_run.orchestrator_run_id != run.id:
        raise HTTPException(status_code=404, detail="Flow node run not found")
    return {
        "run": serialize_flow_run(run),
        "node_run": serialize_flow_node_run(node_run, detail=True),
    }


async def list_flow_node_runs(db: AsyncSession, *, run_id: str) -> list[FlowNodeRun]:
    result = await db.execute(
        select(FlowNodeRun)
        .where(FlowNodeRun.orchestrator_run_id == run_id)
        .order_by(FlowNodeRun.created_at.asc())
    )
    return list(result.scalars().all())


def serialize_flow_run(run: OrchestratorAgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "pattern_type": run.pattern_type,
        "session_id": run.session_id,
        "parent_session_id": run.parent_session_id,
        "project_id": run.project_id,
        "flow_definition_version_id": run.flow_definition_version_id,
        "flow_node_id": run.flow_node_id,
        "current_step_index": run.current_step_index,
        "total_steps": run.total_steps,
        "child_session_ids": list(run.child_session_ids_json or []),
        "merged_output_json": redact_trace_value(run.merged_output_json),
        "progress": redact_trace_value(flow_run_progress_state(run)),
        "runtime_lease": redact_trace_value(flow_run_lease_state(run)),
        "plan": redact_trace_value(flow_run_plan_state(run)),
        "validation_loop": redact_trace_value(validation_loop_state(run)),
        "acceptance": redact_trace_value(runtime_acceptance_state(run)),
        "failure": redact_trace_value(runtime_failure_state(run)),
        "last_error": redact_trace_value(run.last_error),
        "created_at": _iso(run.created_at),
        "completed_at": _iso(run.completed_at),
    }


def serialize_flow_node_run(node_run: FlowNodeRun, *, detail: bool = False) -> dict[str, Any]:
    payload = {
        "id": node_run.id,
        "flow_run_id": node_run.orchestrator_run_id,
        "flow_definition_version_id": node_run.flow_definition_version_id,
        "node_id": node_run.node_id,
        "node_type": node_run.node_type,
        "status": node_run.status,
        "attempt": node_run.attempt,
        "error": redact_trace_value(node_run.error),
        "evidence_summary": redact_trace_value(node_run.evidence_summary_json),
        "artifact_refs": redact_trace_value(node_run.artifact_refs_json),
        "trace_refs": redact_trace_value(node_run.trace_refs_json),
        "decision_trace": redact_trace_value(
            decision_trace_from_refs(dict(node_run.trace_refs_json or {})),
            compact=not detail,
        ),
        "token_usage": redact_trace_value(node_run.token_usage_json),
        "cost_estimate": redact_trace_value(node_run.cost_estimate_json),
        "started_at": _iso(node_run.started_at),
        "completed_at": _iso(node_run.completed_at),
        "duration_ms": _duration_ms(node_run.started_at, node_run.completed_at),
    }
    payload["input"] = redact_trace_value(node_run.input_json, compact=not detail)
    payload["output"] = redact_trace_value(node_run.output_json, compact=not detail)
    return payload


def redact_trace_value(value: Any, *, compact: bool = False) -> Any:
    return _redact(value, compact=compact, depth=0)


def _redact(value: Any, *, compact: bool, depth: int) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _redact_string(value, compact=compact)
    if isinstance(value, list):
        max_items = min(MAX_LIST_ITEMS, 12) if compact else MAX_LIST_ITEMS
        items = [_redact(item, compact=compact, depth=depth + 1) for item in value[:max_items]]
        if len(value) > max_items:
            items.append({"_truncated_items": len(value) - max_items})
        return items
    if isinstance(value, dict):
        max_items = min(MAX_DICT_ITEMS, 24) if compact else MAX_DICT_ITEMS
        redacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            key_text = str(key)
            if index >= max_items:
                redacted["_truncated_keys"] = len(value) - max_items
                break
            if SECRET_KEY_PATTERN.search(key_text):
                redacted[key_text] = REDACTED
            elif depth > 8:
                redacted[key_text] = "[max-depth]"
            else:
                redacted[key_text] = _redact(item, compact=compact, depth=depth + 1)
        return redacted
    return str(value)


def _redact_string(value: str, *, compact: bool) -> str:
    if SECRET_VALUE_PATTERN.search(value):
        value = SECRET_VALUE_PATTERN.sub(REDACTED, value)
    limit = 420 if compact else MAX_STRING_LENGTH
    if len(value) <= limit:
        return value
    return f"{value[:limit]}... [truncated {len(value) - limit} chars]"


def _duration_ms(started_at: datetime | None, completed_at: datetime | None) -> int | None:
    if started_at is None or completed_at is None:
        return None
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


__all__ = [
    "get_flow_node_run_trace",
    "get_flow_run_trace",
    "list_flow_node_runs",
    "redact_trace_value",
    "serialize_flow_node_run",
    "serialize_flow_run",
]
