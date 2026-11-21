"""Flow version builders and node run accessors shared by the flow orchestration runner tests."""

from sqlalchemy import select

from app.models.runtime.flow_definition import FlowDefinition, FlowDefinitionVersion, FlowNodeRun


def _make_v2_flow_version(db, version_id, flow_id, flow_key, nodes, edges):
    flow = FlowDefinition(
        id=flow_id,
        key=flow_key,
        name=f"Test {flow_key}",
        status="published",
        is_active=True,
        project_id=None,
        created_by="u1",
    )
    db.add(flow)
    version = FlowDefinitionVersion(
        id=version_id,
        flow_id=flow_id,
        version=1,
        status="published",
        definition_json={"schema_version": "2.0", "nodes": nodes, "edges": edges},
        created_by="u1",
    )
    db.add(version)
    return version


async def _node_runs(db, orchestrator_run_id: str) -> list[FlowNodeRun]:
    result = await db.execute(
        select(FlowNodeRun)
        .where(FlowNodeRun.orchestrator_run_id == orchestrator_run_id)
        .order_by(FlowNodeRun.created_at.asc())
    )
    return list(result.scalars().all())
