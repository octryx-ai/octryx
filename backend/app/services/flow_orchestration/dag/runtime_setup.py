"""Runtime setup shared by the entry points: Workspace config, budget and lease for a run that resumes."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import FlowNodeRun, Session
from ....models.agent.orchestrator_agent import OrchestratorAgentRun
from ....models.runtime.flow_definition import FlowDefinitionVersion
from ....time_utils import utc_now
from ...flow_runtime_governance import FlowRuntimeUsage, resolve_flow_runtime_limits
from ...project.service import get_project_config
from ..recovery import resolve_flow_run_lease_seconds, set_flow_run_lease_config
from .context import DagRun, LoopMode
from .graph import FlowGraph
from .model import NODE_STATUS_COMPLETED


async def _load_project_config(db: AsyncSession, project_id: str | None) -> dict[str, Any]:
    # The one place the executor reads Workspace config, so a fresh run and a resume see the same source.
    return await get_project_config(project_id, db)


async def _resumed_dag_run(
    db: AsyncSession,
    *,
    orchestrator_run: OrchestratorAgentRun,
    version: FlowDefinitionVersion,
    graph: FlowGraph,
    existing_node_runs: list[FlowNodeRun],
    user_id: str,
    mode: LoopMode,
    outputs: dict[str, dict[str, Any]],
    skipped: set[str],
) -> DagRun:
    """Rebuild budget, lease and Workspace config for a run continuing from its recorded node attempts."""
    session = await db.get(Session, orchestrator_run.session_id)
    agent_type = session.agent_type if session is not None else "change"
    project_config = await _load_project_config(db, orchestrator_run.project_id)
    limits = resolve_flow_runtime_limits(
        definition=graph.definition,
        version_runtime_settings=dict(version.runtime_settings or {}),
        publish_metadata=dict(version.publish_metadata or {}),
    )
    set_flow_run_lease_config(
        orchestrator_run,
        lease_seconds=resolve_flow_run_lease_seconds(
            definition=graph.definition,
            version_runtime_settings=dict(version.runtime_settings or {}),
            publish_metadata=dict(version.publish_metadata or {}),
        ),
    )
    usage = FlowRuntimeUsage(
        started_at=orchestrator_run.created_at or utc_now(),
        tool_calls=sum(
            1
            for node_run in existing_node_runs
            if node_run.status == NODE_STATUS_COMPLETED and node_run.node_type in {"tool_step", "retrieval"}
        ),
    )
    return DagRun(
        db=db, run=orchestrator_run, version=version, graph=graph, mode=mode, user_id=user_id,
        agent_type=agent_type, project_id=orchestrator_run.project_id, project_config=project_config,
        limits=limits, usage=usage, initial_input={}, outputs=outputs, skipped=skipped,
        previous_node_runs=existing_node_runs,
    )
