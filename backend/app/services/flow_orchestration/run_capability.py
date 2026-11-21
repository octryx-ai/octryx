"""The run capability a flow run's tool nodes dispatch under.

The class comes from the flow version's declaration (``services/run_capability/flow_capability``),
capped by the class of the run that started the flow (a flow started from a chat turn never exceeds
that turn). It is decided once per flow run and recorded on the run
(``routing_policy_json.runtime.run_capability``), so resumed nodes dispatch under the same class
and the run shows where its class came from.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import OrchestratorAgentRun, Session
from ...models.runtime.flow_definition import FlowDefinitionVersion
from ..run_capability.classes import RUN_CAPABILITY_CLASS_KEY, normalize_capability_class
from ..run_capability.declared import (
    SOURCE_RUN_PROFILE,
    DeclaredRunCapability,
    capability_from_run_profile,
    capped_by_parent,
)
from ..run_capability.flow_capability import flow_declared_capability

RUN_CAPABILITY_RUNTIME_KEY = "run_capability"


def _recorded(orchestrator_run: OrchestratorAgentRun) -> DeclaredRunCapability | None:
    runtime = (orchestrator_run.routing_policy_json or {}).get("runtime")
    recorded = runtime.get(RUN_CAPABILITY_RUNTIME_KEY) if isinstance(runtime, dict) else None
    if not isinstance(recorded, dict) or not recorded.get("source"):
        return None
    source = str(recorded["source"])
    if recorded.get("error"):
        return DeclaredRunCapability(capability_class=None, source=source, error=str(recorded["error"]))
    capability_class = normalize_capability_class(recorded.get(RUN_CAPABILITY_CLASS_KEY))
    if capability_class is None:
        return None
    return DeclaredRunCapability(
        capability_class=capability_class, source=source, capped_by_parent=bool(recorded.get("capped_by_parent"))
    )


async def _parent_class(db: AsyncSession, parent_session_id: str | None) -> str | None:
    parent = await db.get(Session, parent_session_id) if parent_session_id else None
    if parent is None:
        return None
    capability = capability_from_run_profile((parent.metadata_ or {}).get("execution_profile"))
    return capability.capability_class if capability.source == SOURCE_RUN_PROFILE else None


async def flow_run_capability(db: AsyncSession, orchestrator_run: OrchestratorAgentRun) -> DeclaredRunCapability:
    """The flow run's class: recorded on the run the first time it is decided."""
    recorded = _recorded(orchestrator_run)
    if recorded is not None:
        return recorded
    version_id = orchestrator_run.flow_definition_version_id
    version = await db.get(FlowDefinitionVersion, version_id) if version_id else None
    declared = flow_declared_capability(dict(version.definition_json or {}) if version is not None else None)
    declared = capped_by_parent(declared, await _parent_class(db, orchestrator_run.parent_session_id))
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = dict(policy.get("runtime") or {})
    runtime[RUN_CAPABILITY_RUNTIME_KEY] = declared.to_metadata()
    policy["runtime"] = runtime
    orchestrator_run.routing_policy_json = policy
    return declared


async def flow_tool_context_capability(db: AsyncSession, orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    """The ``ToolContext.run_capability`` state of the flow run's tool nodes."""
    return (await flow_run_capability(db, orchestrator_run)).tool_context_state()


__all__ = ["RUN_CAPABILITY_RUNTIME_KEY", "flow_run_capability", "flow_tool_context_capability"]
