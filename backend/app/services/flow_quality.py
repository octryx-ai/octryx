from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FlowDefinitionVersion, FlowNodeRun, User
from ..models.agent.orchestrator_agent import OrchestratorAgentRun
from ..models.runtime.workflow_check import WorkflowCheckResult
from .flow_trace import list_flow_node_runs, serialize_flow_node_run, serialize_flow_run

RUNTIME_CANVAS = "canvas"
FLOW_WORKFLOW_PREFIX = "flow:"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


async def get_flow_run_quality_summary(db: AsyncSession, *, run_id: str) -> dict[str, Any]:
    run, version = await _load_flow_run(db, run_id=run_id)
    node_runs = await list_flow_node_runs(db, run_id=run.id)
    summary = _build_quality_summary(run=run, version=version, node_runs=node_runs)
    summary["evaluation_runs"] = await _list_flow_run_evaluations(db, run_id=run.id)
    return summary


async def evaluate_flow_run(
    db: AsyncSession,
    *,
    run_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Record the run's quality as a check result (the canvas evaluation needs no evaluation suite)."""
    del current_user, payload
    run, version = await _load_flow_run(db, run_id=run_id)
    node_runs = await list_flow_node_runs(db, run_id=run.id)
    summary = _build_quality_summary(run=run, version=version, node_runs=node_runs)
    row = WorkflowCheckResult(
        session_id=None,
        trace_id=run.id,
        workflow_key=f"{FLOW_WORKFLOW_PREFIX}{version.flow_id}",
        workflow_version=version.version,
        runtime=RUNTIME_CANVAS,
        state="passed" if summary["status"] == "passed" else "not_verified",
        results_json=[{
            "type": "flow_quality",
            "outcome": summary["status"],
            "blocking": False,
            "description": "Observed quality of the canvas run (nodes, evidence, status)",
            "detail": f"score {summary['score']}",
            "score": summary["score"],
        }],
    )
    db.add(row)
    await db.flush()
    evaluation_run = _evaluation_payload(row)
    await db.commit()
    summary["evaluation_runs"] = await _list_flow_run_evaluations(db, run_id=run.id)
    return {"quality_summary": summary, "evaluation_run": evaluation_run}


async def _load_flow_run(
    db: AsyncSession,
    *,
    run_id: str,
) -> tuple[OrchestratorAgentRun, FlowDefinitionVersion]:
    run = await db.get(OrchestratorAgentRun, run_id)
    if run is None or not run.flow_definition_version_id:
        raise HTTPException(status_code=404, detail="Flow run not found")
    version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Flow definition version not found")
    return run, version


def _evaluation_payload(row: WorkflowCheckResult) -> dict[str, Any]:
    results = row.results_json if isinstance(row.results_json, list) else []
    passed = row.state == "passed"
    score = (results[0] if results and isinstance(results[0], dict) else {}).get("score")
    return {
        "id": row.id,
        "status": "completed",
        "passed_count": 1 if passed else 0,
        "failed_count": 0 if passed else 1,
        "average_score": score if isinstance(score, int | float) else None,
        "started_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _list_flow_run_evaluations(db: AsyncSession, *, run_id: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(WorkflowCheckResult)
            .where(WorkflowCheckResult.runtime == RUNTIME_CANVAS, WorkflowCheckResult.trace_id == run_id)
            .order_by(WorkflowCheckResult.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return [_evaluation_payload(row) for row in rows]


def _build_quality_summary(
    *,
    run: OrchestratorAgentRun,
    version: FlowDefinitionVersion,
    node_runs: list[FlowNodeRun],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    evidence_count = 0
    artifact_count = 0
    total_tokens = 0
    total_cost = 0.0
    warnings: list[dict[str, str]] = []
    failed_nodes: list[str] = []
    for node_run in node_runs:
        status_counts[node_run.status] = status_counts.get(node_run.status, 0) + 1
        if node_run.status in {"failed", "cancelled"} or node_run.error:
            failed_nodes.append(node_run.node_id)
        evidence_count += _evidence_count(node_run.evidence_summary_json)
        artifact_count += len(_list(node_run.artifact_refs_json))
        total_tokens += _sum_numeric(
            node_run.token_usage_json,
            keys={"tokens", "total_tokens", "input_tokens", "output_tokens"},
        )
        total_cost += _sum_numeric(node_run.cost_estimate_json, keys={"cost", "usd", "total_cost_usd"})
    if not node_runs:
        warnings.append({"code": "no_node_runs", "message": "The flow run has no persisted node run evidence."})
    if evidence_count == 0:
        warnings.append({"code": "missing_evidence", "message": "No node-level evidence summaries were recorded."})
    if failed_nodes:
        warnings.append({"code": "failed_nodes", "message": "One or more nodes failed: " + ", ".join(failed_nodes[:8])})
    if run.status != "completed":
        warnings.append({"code": "run_not_completed", "message": f"Run status is {run.status}."})
    score = _quality_score(
        run_status=run.status,
        node_runs=node_runs,
        failed_nodes=failed_nodes,
        evidence_count=evidence_count,
    )
    return {
        "run": serialize_flow_run(run),
        "flow_id": version.flow_id,
        "flow_definition_version_id": version.id,
        "status": "passed" if score >= 0.85 else "warning" if score >= 0.6 else "failed",
        "score": score,
        "node_count": len(node_runs),
        "node_status_counts": status_counts,
        "failed_nodes": failed_nodes,
        "evidence_count": evidence_count,
        "artifact_count": artifact_count,
        "token_usage": {"total_tokens": total_tokens},
        "cost_estimate": {"total_cost_usd": round(total_cost, 6)},
        "warnings": warnings,
        "node_runs": [serialize_flow_node_run(node_run) for node_run in node_runs],
    }


def _evidence_count(value: Any) -> int:
    payload = _dict(value)
    count = payload.get("count")
    if isinstance(count, int | float):
        return max(0, int(count))
    if payload:
        return 1
    return 0


def _sum_numeric(value: Any, *, keys: set[str]) -> float:
    if isinstance(value, dict):
        total = 0.0
        for key, item in value.items():
            if isinstance(item, int | float) and str(key) in keys:
                total += float(item)
            elif isinstance(item, dict | list):
                total += _sum_numeric(item, keys=keys)
        return total
    if isinstance(value, list):
        return sum(_sum_numeric(item, keys=keys) for item in value)
    return 0


def _quality_score(
    *,
    run_status: str,
    node_runs: list[FlowNodeRun],
    failed_nodes: list[str],
    evidence_count: int,
) -> float:
    if run_status in {"failed", "cancelled"}:
        return 0.0
    if run_status == "paused":
        return 0.5
    if not node_runs:
        return 0.2
    score = 1.0
    if failed_nodes:
        score -= 0.45
    if evidence_count == 0:
        score -= 0.2
    skipped = sum(1 for node_run in node_runs if node_run.status == "skipped")
    if skipped:
        score -= min(0.2, skipped / max(len(node_runs), 1) * 0.2)
    return max(0.0, round(score, 4))


def _summary_text(summary: dict[str, Any]) -> str:
    warnings = ", ".join(item["code"] for item in summary["warnings"]) or "none"
    return (
        f"Flow run status {summary['run']['status']}. "
        f"Quality status {summary['status']} with score {summary['score']}. "
        f"Nodes {summary['node_count']} and statuses {summary['node_status_counts']}. "
        f"Evidence items {summary['evidence_count']}; artifacts {summary['artifact_count']}. "
        f"Warnings: {warnings}."
    )


__all__ = [
    "evaluate_flow_run",
    "get_flow_run_quality_summary",
]
