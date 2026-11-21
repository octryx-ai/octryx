"""Persistence of node attempts (``FlowNodeRun`` rows) and their audit events."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import FlowNodeRun
from ....models.agent.orchestrator_agent import OrchestratorAgentRun
from ....models.runtime.flow_definition import FlowDefinitionVersion
from ....time_utils import utc_now
from ..decision_trace import build_node_decision_trace
from .evidence import _artifact_refs, _cost_estimate, _evidence_summary, _token_usage, _trace_refs
from .model import (
    NODE_STATUS_COMPLETED,
    NODE_STATUS_FAILED,
    NODE_STATUS_PAUSED,
    NODE_STATUS_RUNNING,
    NODE_STATUS_SKIPPED,
)
from .run_state import _audit_flow_event, _commit_flow_checkpoint


async def _start_node_run(
    db: AsyncSession,
    orchestrator_run: OrchestratorAgentRun,
    version: FlowDefinitionVersion,
    node: dict[str, Any],
    input_snapshot: dict[str, Any],
    *,
    user_id: str,
    attempt: int = 1,
) -> FlowNodeRun:
    node_run = FlowNodeRun(
        orchestrator_run_id=orchestrator_run.id,
        flow_definition_version_id=version.id,
        node_id=str(node.get("id") or ""),
        node_type=str(node.get("type") or ""),
        status=NODE_STATUS_RUNNING,
        attempt=attempt,
        input_json=input_snapshot,
        trace_refs_json={
            "node_label": node.get("label"),
            "node_type": node.get("type"),
            "status_transition": ["pending", "running"],
        },
        started_at=utc_now(),
    )
    db.add(node_run)
    await db.flush()
    await _audit_flow_event(
        db,
        user_id=user_id,
        session_id=orchestrator_run.session_id,
        action="flow.node_started",
        run=orchestrator_run,
        node_id=node_run.node_id,
        details={"node_type": node_run.node_type, "input_keys": sorted(input_snapshot.keys())[:30]},
    )
    await _commit_flow_checkpoint(db, orchestrator_run, node_run)
    return node_run


async def _complete_node_run(
    db: AsyncSession,
    node_run: FlowNodeRun,
    node: dict[str, Any],
    output: dict[str, Any],
    *,
    orchestrator_run: OrchestratorAgentRun,
    user_id: str,
) -> None:
    evidence_summary = _evidence_summary(output)
    artifact_refs = _artifact_refs(output)
    node_run.status = NODE_STATUS_COMPLETED
    node_run.output_json = output
    node_run.evidence_summary_json = evidence_summary
    node_run.artifact_refs_json = artifact_refs
    node_run.trace_refs_json = _trace_refs(
        node,
        output,
        status=NODE_STATUS_COMPLETED,
        input_snapshot=dict(node_run.input_json or {}),
        evidence_summary=evidence_summary,
        artifact_refs=artifact_refs,
    )
    node_run.token_usage_json = _token_usage(output)
    node_run.cost_estimate_json = _cost_estimate(output)
    node_run.completed_at = utc_now()
    await _audit_flow_event(
        db,
        user_id=user_id,
        session_id=orchestrator_run.session_id,
        action="flow.node_completed",
        run=orchestrator_run,
        node_id=node_run.node_id,
        details={"node_type": node_run.node_type, "output_keys": sorted(output.keys())[:30]},
    )
    await db.flush()


async def _pause_node_run(
    db: AsyncSession,
    node_run: FlowNodeRun,
    node: dict[str, Any],
    output: dict[str, Any],
    *,
    orchestrator_run: OrchestratorAgentRun,
    user_id: str,
) -> None:
    evidence_summary = _evidence_summary(output)
    artifact_refs = _artifact_refs(output)
    node_run.status = NODE_STATUS_PAUSED
    node_run.output_json = output
    node_run.evidence_summary_json = evidence_summary
    node_run.artifact_refs_json = artifact_refs
    node_run.trace_refs_json = _trace_refs(
        node,
        output,
        status=NODE_STATUS_PAUSED,
        input_snapshot=dict(node_run.input_json or {}),
        evidence_summary=evidence_summary,
        artifact_refs=artifact_refs,
    )
    node_run.completed_at = utc_now()
    await _audit_flow_event(
        db,
        user_id=user_id,
        session_id=orchestrator_run.session_id,
        action="flow.node_paused",
        run=orchestrator_run,
        node_id=node_run.node_id,
        details={"node_type": node_run.node_type, "reason": str(output.get("reason") or "")},
    )
    await db.flush()


async def _fail_node_run(
    db: AsyncSession,
    node_run: FlowNodeRun,
    node: dict[str, Any],
    error: str,
    *,
    orchestrator_run: OrchestratorAgentRun,
    user_id: str,
) -> None:
    output = {"error": error}
    node_run.status = NODE_STATUS_FAILED
    node_run.error = error
    node_run.trace_refs_json = _trace_refs(
        node,
        output,
        status=NODE_STATUS_FAILED,
        input_snapshot=dict(node_run.input_json or {}),
        evidence_summary={},
        artifact_refs=[],
    )
    node_run.completed_at = utc_now()
    await _audit_flow_event(
        db,
        user_id=user_id,
        session_id=orchestrator_run.session_id,
        action="flow.node_failed",
        run=orchestrator_run,
        node_id=node_run.node_id,
        details={"node_type": node_run.node_type, "error": error},
    )
    await db.flush()


async def _persist_skipped_node(
    db: AsyncSession,
    orchestrator_run: OrchestratorAgentRun,
    version: FlowDefinitionVersion,
    node: dict[str, Any],
    *,
    reason: str,
) -> None:
    output = {"reason": reason}
    trace_refs = {
        "node_label": node.get("label"),
        "node_type": node.get("type"),
        "status_transition": ["pending", "skipped"],
        "reason": reason,
        "decision_trace": build_node_decision_trace(
            node=node,
            input_snapshot={},
            output=output,
            status=NODE_STATUS_SKIPPED,
            evidence_summary={},
            artifact_refs=[],
        ),
    }
    node_run = FlowNodeRun(
        orchestrator_run_id=orchestrator_run.id,
        flow_definition_version_id=version.id,
        node_id=str(node.get("id") or ""),
        node_type=str(node.get("type") or ""),
        status=NODE_STATUS_SKIPPED,
        output_json=output,
        trace_refs_json={key: value for key, value in trace_refs.items() if value not in (None, "", [], {})},
        completed_at=utc_now(),
    )
    db.add(node_run)
    await db.flush()


async def _flow_node_runs(db: AsyncSession, *, run_id: str) -> list[FlowNodeRun]:
    result = await db.execute(
        select(FlowNodeRun)
        .where(FlowNodeRun.orchestrator_run_id == run_id)
        .order_by(FlowNodeRun.created_at.asc())
    )
    return list(result.scalars().all())


def _next_node_attempt(existing_node_runs: list[FlowNodeRun], *, node_id: str) -> int:
    attempts = [int(node_run.attempt or 1) for node_run in existing_node_runs if node_run.node_id == node_id]
    return (max(attempts) + 1) if attempts else 1
