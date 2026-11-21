"""Kubernetes topology snapshots and code graph results with their evidence contracts."""

import uuid

import pytest
from sqlalchemy import select

from app.agent.loops.outcome._loop_evidence_contracts import (
    build_incomplete_evidence_contract_reminder,
    critical_incomplete_evidence_contracts,
)
from app.models import Session, User
from app.services.tool_result_compression import compress_tool_result_for_model


@pytest.mark.asyncio
async def test_kubernetes_topology_snapshot_is_compressed_with_evidence_contract(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="kubernetes_topology_snapshot",
        result={
            "source": "kubectl",
            "generated_at": "2026-06-07T10:00:00+00:00",
            "scope": {"namespace": "acme-orders", "all_namespaces": False},
            "topology_summary": {
                "resource_node_count": 3,
                "edge_count": 2,
                "selected_resource_node_count": 3,
                "selected_edge_count": 2,
                "node_counts_by_type": {"deployment": 1, "service": 1, "pod": 1},
            },
            "nodes": [{"ref": f"node-{index}", "payload": "x" * 500} for index in range(100)],
            "edges": [{"source_ref": "node-0", "target_ref": "node-1", "relationship": "selects"}],
            "diagram_brief": {
                "mode": "full",
                "selected_nodes": [
                    {"ref": "node-0", "type": "deployment", "label": "api"},
                    {"ref": "node-1", "type": "service", "label": "api-service"},
                    {"ref": "node-2", "type": "pod", "label": "api-123"},
                ],
                "selected_edges": [
                    {"source_ref": "node-0", "target_ref": "node-2", "relationship": "owns"},
                    {"source_ref": "node-1", "target_ref": "node-2", "relationship": "selects"},
                ],
                "omitted_node_count": 0,
                "omitted_edge_count": 0,
            },
            "warnings": ["minor collection warning"],
        },
    )

    assert "nodes" not in compressed
    assert "edges" not in compressed
    assert compressed["topology_summary"]["resource_node_count"] == 3
    assert len(compressed["diagram_brief"]["selected_edges"]) == 2
    contract = compressed["evidence_contract"]
    assert contract["status"] == "passed"
    assert contract["tool_name"] == "kubernetes_topology_snapshot"
    assert contract["strategy"] == "kubernetes_topology_snapshot_summary"
    assert contract["missing_paths"] == []


@pytest.mark.asyncio
async def test_kubernetes_topology_evidence_contract_failure_is_critical(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="kubernetes_topology_snapshot",
        result={
            "source": "kubectl",
            "scope": {"namespace": "acme-orders", "all_namespaces": False},
            "topology_summary": {
                "resource_node_count": 0,
                "edge_count": 0,
                "selected_resource_node_count": 0,
                "selected_edge_count": 0,
                "node_counts_by_type": {},
            },
            "diagram_brief": {
                "mode": "full",
                "selected_nodes": [],
                "selected_edges": [],
                "omitted_node_count": 0,
                "omitted_edge_count": 0,
            },
        },
    )

    contract = compressed["evidence_contract"]
    assert contract["status"] == "failed"
    assert contract["missing_paths"] == ["generated_at"]
    incomplete = critical_incomplete_evidence_contracts(
        [
            {
                "artifact_id": "artifact-k8s-1",
                "tool_name": "kubernetes_topology_snapshot",
                "compact_result": compressed,
            }
        ]
    )
    assert incomplete == [
        {
            "artifact_id": "artifact-k8s-1",
            "tool_name": "kubernetes_topology_snapshot",
            "missing_paths": ["generated_at"],
            "hard_capped": False,
            "evidence_state": "incomplete_compact_evidence",
        }
    ]


@pytest.mark.asyncio
async def test_code_graph_node_tool_result_gets_evidence_contract(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="code_node",
        result={
            "repository": {"id": "repo-1", "name": "octryx"},
            "graph": {
                "status": "completed",
                "backend": "native",
                "node_count": 12,
                "edge_count": 9,
            },
            "graph_backend": "native",
            "node": {"id": "node-1", "name": "ReportBuilder", "path": "src/report_builder.py"},
            "detail": {"callees": [], "callers": []},
            "matches": [{"id": "node-1", "name": "ReportBuilder", "path": "src/report_builder.py"}],
            "match_count": 1,
            "query": {"query": "ReportBuilder"},
        },
    )

    contract = compressed["evidence_contract"]
    assert contract["status"] == "passed"
    assert contract["tool_name"] == "code_node"
    assert contract["strategy"] == "fallback"
    assert contract["missing_paths"] == []


@pytest.mark.asyncio
async def test_code_graph_trace_no_path_result_gets_evidence_contract(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="code_trace",
        result={
            "repository": {"id": "repo-1", "name": "octryx"},
            "graph": {
                "status": "completed",
                "backend": "native",
                "node_count": 12,
                "edge_count": 9,
            },
            "graph_backend": "native",
            "status": "no_path",
            "source_node": {"id": "node-1", "name": "handler", "path": "src/app.py"},
            "target_node": {"id": "node-2", "name": "dynamicSink", "path": "src/dynamic.py"},
            "path": [],
            "edges": [],
            "hops": [],
            "hop_count": 0,
            "truncated": False,
            "no_path_reason": "no static path found",
            "limits": {"max_depth": 3, "max_expansions": 500},
        },
    )

    contract = compressed["evidence_contract"]
    assert contract["status"] == "passed"
    assert contract["tool_name"] == "code_trace"
    assert contract["missing_paths"] == []


@pytest.mark.asyncio
async def test_code_graph_context_hard_cap_is_critical_incomplete_evidence(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="code_context",
        result={
            "repository": {"id": "repo-1", "name": "octryx"},
            "graph": {
                "status": "completed",
                "backend": "native",
                "node_count": 120,
                "edge_count": 90,
            },
            "graph_backend": "native",
            "status": "ready",
            "start_node": {"id": "node-1", "name": "ReportBuilder", "path": "src/report_builder.py"},
            "context_nodes": [
                {
                    "node": {"id": f"node-{index}", "name": f"symbol_{index}", "path": "src/report_builder.py"},
                    "source_chunk": {"content": "def huge_context():\n" + ("x = 1\n" * 500)},
                }
                for index in range(40)
            ],
            "context_edges": [{"id": "edge-1", "relation": "calls"}],
            "context_files": [{"path": "src/report_builder.py", "source_chunks": []}],
            "relationship_map": [{"source": "node-1", "target": "node-2", "relation": "calls"}],
            "not_shown_candidates": [],
            "budget": {"requested_chars": 6000, "used_chars": 6000},
            "retrieval_provenance": {"matched_symbols": [{"name": "ReportBuilder"}]},
            "filters": {"direction": "both"},
            "limits": {"depth": 2, "max_nodes": 50},
        },
    )

    contract = compressed["evidence_contract"]
    assert contract["status"] == "failed"
    assert contract["hard_capped"] is True
    incomplete = critical_incomplete_evidence_contracts(
        [
            {
                "artifact_id": "artifact-code-1",
                "tool_name": "code_context",
                "compact_result": compressed,
            }
        ]
    )
    assert incomplete == [
        {
            "artifact_id": "artifact-code-1",
            "tool_name": "code_context",
            "missing_paths": contract["missing_paths"],
            "hard_capped": True,
            "evidence_state": "incomplete_compact_evidence",
        }
    ]
    assert "CodeGraph" in build_incomplete_evidence_contract_reminder(incomplete)
