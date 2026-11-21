"""Agent-chain rows as API payloads, and template steps normalized on write."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException

from ...models import AgentChainRun, AgentChainTemplate


def _serialize_template(row: AgentChainTemplate) -> dict[str, Any]:
    steps = list(row.steps_json or [])
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "project_id": row.project_id,
        "is_active": bool(row.is_active),
        "steps": steps,
        "step_count": len(steps),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_run(row: AgentChainRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "template_id": row.template_id,
        "project_id": row.project_id,
        "started_by": row.started_by,
        "status": row.status,
        "input_payload": dict(row.input_payload or {}),
        "output_payload": dict(row.output_payload or {}),
        "step_results": list(row.step_results or []),
        "error": row.error,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _normalize_steps(raw_steps: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_steps, start=1):
        item = dict(raw or {})
        step_id = str(item.get("id") or "").strip() or f"step_{index}"
        name = str(item.get("name") or "").strip() or f"Step {index}"
        agent_type = str(item.get("agent_type") or "").strip()
        if not agent_type:
            raise HTTPException(status_code=422, detail=f"steps[{index - 1}].agent_type is required")
        execution_mode = str(item.get("execution_mode") or "sequential").strip().lower() or "sequential"
        if execution_mode not in {"sequential", "parallel"}:
            raise HTTPException(
                status_code=422,
                detail=f"steps[{index - 1}].execution_mode must be sequential or parallel",
            )
        parallel_group = str(item.get("parallel_group") or "").strip() or None
        normalized.append(
            {
                "id": step_id,
                "name": name,
                "agent_type": agent_type,
                "thinking_level": str(item.get("thinking_level") or "").strip() or None,
                "execution_mode": execution_mode,
                "parallel_group": parallel_group,
                "input_mapping": item.get("input_mapping"),
                "output_mapping": dict(item.get("output_mapping") or {}),
            }
        )
    return normalized
