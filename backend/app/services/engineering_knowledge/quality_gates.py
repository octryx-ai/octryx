"""Quality gates and dashboard metrics for Engineering Knowledge."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgeGraphEdge,
    EngineeringKnowledgeGraphNode,
)
from ._quality_gate_checks import QualityGateResult, _gate, _quality_policy, _quality_score, _source_refs, _static_gates
from .graph_retrieval import search_engineering_knowledge_graph

DEFAULT_EVALUATION_SCENARIOS = [
    {
        "key": "vulnerability_fix",
        "label": "Vulnerability fix",
        "required_signals": ["cve", "affected_package", "fixed_version", "source_evidence"],
    },
    {
        "key": "framework_upgrade",
        "label": "Framework upgrade",
        "required_signals": ["source_version", "target_version", "compatibility_evidence"],
    },
    {
        "key": "build_failure",
        "label": "Build failure",
        "required_signals": ["pipeline", "failing_stage", "known_fix", "verification"],
    },
    {
        "key": "flaky_ci",
        "label": "Flaky CI",
        "required_signals": ["failure_pattern", "frequency", "mitigation", "owner"],
    },
    {
        "key": "reviewer_selection",
        "label": "Reviewer selection",
        "required_signals": ["technology", "repository", "reviewer_evidence"],
    },
    {
        "key": "repository_test_selection",
        "label": "Repository test selection",
        "required_signals": ["repository", "test_scope", "trigger", "confidence"],
    },
]


async def evaluate_engineering_knowledge_node_quality(
    db: AsyncSession,
    node: EngineeringKnowledgeGraphNode,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_policy = _quality_policy(policy)
    source_refs = _source_refs(node.source_refs_json)
    properties = dict(node.properties_json or {})
    lifecycle = dict(properties.get("lifecycle") or {})
    gates = _static_gates(node, safe_policy=safe_policy, source_refs=source_refs, lifecycle=lifecycle)
    contradiction_gate = await _contradiction_gate(db, node)
    gates.append(contradiction_gate)
    retrieval_gate = await _retrieval_precision_gate(db, node)
    gates.append(retrieval_gate)
    failed = [gate for gate in gates if gate.status == "failed" and gate.severity == "blocking"]
    warnings = [gate for gate in gates if gate.status == "failed" and gate.severity == "warning"]
    return {
        "node_id": node.id,
        "node_key": node.node_key,
        "passed": not failed,
        "status": "passed" if not failed else "failed",
        "quality_score": _quality_score(gates),
        "blocking_count": len(failed),
        "warning_count": len(warnings),
        "gates": [gate.as_dict() for gate in gates],
        "blockers": [gate.as_dict() for gate in failed],
        "warnings": [gate.as_dict() for gate in warnings],
    }


async def get_engineering_knowledge_quality_dashboard(
    db: AsyncSession,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 50), 200))
    status_counts = await _count_by(db, EngineeringKnowledgeGraphNode.status)
    trust_counts = await _count_by(db, EngineeringKnowledgeGraphNode.trust_level)
    candidate_rows = (
        (
            await db.execute(
                select(EngineeringKnowledgeGraphNode)
                .where(
                    EngineeringKnowledgeGraphNode.status.in_(["active", "stale", "expired", "retracted"]),
                )
                .order_by(EngineeringKnowledgeGraphNode.updated_at.desc())
                .limit(safe_limit)
            )
        )
        .scalars()
        .all()
    )
    evaluated = [await evaluate_engineering_knowledge_node_quality(db, node) for node in candidate_rows]
    failures_by_gate: dict[str, int] = {}
    for report in evaluated:
        for blocker in report["blockers"]:
            key = str(blocker.get("key") or "unknown")
            failures_by_gate[key] = failures_by_gate.get(key, 0) + 1
    return {
        "status_counts": status_counts,
        "trust_counts": trust_counts,
        "usage": {
            "retrieval_miss_count": None,
            "retrieval_miss_instrumented": False,
            "retrieval_miss_note": "Engineering Knowledge Graph retrieval misses are not persisted yet.",
        },
        "quality": {
            "evaluated_count": len(evaluated),
            "passed_count": sum(1 for report in evaluated if report["passed"]),
            "failed_count": sum(1 for report in evaluated if not report["passed"]),
            "failures_by_gate": failures_by_gate,
        },
        "evaluation_scenarios": DEFAULT_EVALUATION_SCENARIOS,
        "sample_reports": evaluated[:safe_limit],
    }


async def _contradiction_gate(db: AsyncSession, node: EngineeringKnowledgeGraphNode) -> QualityGateResult:
    conflict_count = int(
        (
            await db.execute(
                select(func.count(EngineeringKnowledgeGraphEdge.id)).where(
                    EngineeringKnowledgeGraphEdge.status == "active",
                    EngineeringKnowledgeGraphEdge.edge_type == "conflicts_with",
                    or_(
                        EngineeringKnowledgeGraphEdge.source_node_id == node.id,
                        EngineeringKnowledgeGraphEdge.target_node_id == node.id,
                    ),
                )
            )
        ).scalar_one()
        or 0
    )
    return _gate(
        "contradiction_detection",
        "Contradiction detection",
        conflict_count == 0,
        f"{conflict_count} active conflicting graph relation(s) found.",
        {"conflict_edge_count": conflict_count},
    )


async def _retrieval_precision_gate(db: AsyncSession, node: EngineeringKnowledgeGraphNode) -> QualityGateResult:
    if node.status != "active":
        return _gate(
            "retrieval_precision",
            "Retrieval precision",
            False,
            "Fact is not active and must not be retrieved by agents.",
            {"status": node.status},
            severity="warning",
        )
    result = await search_engineering_knowledge_graph(
        db,
        query=node.display_name or node.node_key,
        project_ids=[node.workspace_id] if node.workspace_id else [],
        repository_id=node.repository_id,
        allowed_classifications=["public", "internal"],
        include_silver=True,
        limit=10,
    )
    keys = {item["id"] for item in result["results"]}
    return _gate(
        "retrieval_precision",
        "Retrieval precision",
        node.id in keys,
        "Fact is returned by scoped retrieval." if node.id in keys else "Fact is not returned by scoped retrieval.",
        {"retrieved_count": result["count"], "query": result["query"]},
        severity="warning",
    )


async def _count_by(db: AsyncSession, column: Any) -> dict[str, int]:
    rows = (await db.execute(select(column, func.count()).group_by(column))).all()
    return {str(key): int(count or 0) for key, count in rows}
