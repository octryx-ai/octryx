"""Flow orchestration runner: loads a FlowDefinitionVersion and runs it on the 2.0 DAG executor.

Only schema 2.0 definitions run; any other ``schema_version`` is a closed refusal
(``flow_version_unsupported_schema``, see ``flow_version_state.ensure_runnable``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flow_orchestration.dag.execute import execute_v2_flow_dag

from ...models.agent.orchestrator_agent import OrchestratorAgentRun
from ..flow_version_state import ensure_runnable, load_flow_version


async def execute_flow_version(
    db: AsyncSession,
    *,
    flow_version_id: str,
    parent_session_id: str | None = None,
    project_id: str | None = None,
    triggered_by_node_id: str | None = None,
    initial_input: dict[str, Any] | None = None,
    user_id: str = "system",
    agent_type: str = "change",
    # Not used by the DAG executor; the agent engine's flow-session dispatch still passes them.
    runtime_target_id: str | None = None,
    thinking_level: str | None = None,
    agent_definition: dict[str, Any] | None = None,
) -> OrchestratorAgentRun:
    """Run a flow version on the DAG executor and return its OrchestratorAgentRun.

    Unknown, archived, empty, phased, fragment and non-2.0 versions are closed refusals
    (``FlowVersionStateError``).
    """
    version = await load_flow_version(db, flow_version_id)
    ensure_runnable(version)
    return await execute_v2_flow_dag(
        db, version=version, parent_session_id=parent_session_id, project_id=project_id,
        triggered_by_node_id=triggered_by_node_id, initial_input=initial_input, user_id=user_id,
        agent_type=agent_type,
    )


__all__ = ["execute_flow_version"]
