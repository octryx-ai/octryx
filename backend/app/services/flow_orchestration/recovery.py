from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.agent.orchestrator_agent import (
    ORCHESTRATOR_STATUS_FAILED,
    ORCHESTRATOR_STATUS_RUNNING,
    ORCHESTRATOR_STATUS_WAITING_CHILDREN,
    ORCHESTRATOR_STATUS_WAITING_REVIEW,
    OrchestratorAgentRun,
)
from ...time_utils import utc_now

DEFAULT_FLOW_RUN_LEASE_SECONDS = 3600
MIN_FLOW_RUN_LEASE_SECONDS = 60
MAX_FLOW_RUN_LEASE_SECONDS = 8 * 60 * 60
RECOVERABLE_FLOW_STATUSES = {
    ORCHESTRATOR_STATUS_RUNNING,
    ORCHESTRATOR_STATUS_FAILED,
    ORCHESTRATOR_STATUS_WAITING_CHILDREN,
    ORCHESTRATOR_STATUS_WAITING_REVIEW,
}


def resolve_flow_run_lease_seconds(
    *,
    definition: dict[str, Any],
    version_runtime_settings: dict[str, Any] | None,
    publish_metadata: dict[str, Any] | None = None,
) -> int:
    merged: dict[str, Any] = {}
    metadata = publish_metadata if isinstance(publish_metadata, dict) else {}
    for source in (
        definition.get("runtime_settings") if isinstance(definition.get("runtime_settings"), dict) else {},
        version_runtime_settings if isinstance(version_runtime_settings, dict) else {},
        metadata.get("budget") if isinstance(metadata.get("budget"), dict) else {},
        metadata.get("runtime") if isinstance(metadata.get("runtime"), dict) else {},
    ):
        merged.update(source)
    configured = _optional_int(
        merged.get("flow_run_lease_seconds")
        or merged.get("lease_seconds")
        or merged.get("heartbeat_lease_seconds")
        or merged.get("continuation_lease_seconds")
    )
    if configured is None:
        return DEFAULT_FLOW_RUN_LEASE_SECONDS
    return max(MIN_FLOW_RUN_LEASE_SECONDS, min(configured, MAX_FLOW_RUN_LEASE_SECONDS))


def set_flow_run_lease_config(orchestrator_run: OrchestratorAgentRun, *, lease_seconds: int) -> None:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = dict(policy.get("runtime") or {})
    runtime["lease_seconds"] = max(MIN_FLOW_RUN_LEASE_SECONDS, min(int(lease_seconds), MAX_FLOW_RUN_LEASE_SECONDS))
    policy["runtime"] = runtime
    orchestrator_run.routing_policy_json = policy


def touch_flow_run_lease(
    orchestrator_run: OrchestratorAgentRun,
    *,
    node_id: str,
    phase: str,
    owner: str = "flow_dag",
    now: datetime | None = None,
) -> None:
    current = now or utc_now()
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = dict(policy.get("runtime") or {})
    lease_seconds = _lease_seconds_from_policy(policy)
    runtime["progress"] = {
        "current_node_id": node_id,
        "phase": phase,
        "checkpointed_at": current.isoformat(),
    }
    runtime["lease"] = {
        "owner": owner,
        "status": "active" if phase not in {"completed", "failed", "cancelled"} else "terminal",
        "last_heartbeat_at": current.isoformat(),
        "lease_expires_at": (current + timedelta(seconds=lease_seconds)).isoformat(),
        "lease_seconds": lease_seconds,
    }
    policy["runtime"] = runtime
    orchestrator_run.routing_policy_json = policy


def flow_run_progress_state(orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    runtime = _runtime_policy(orchestrator_run)
    progress = runtime.get("progress")
    return dict(progress) if isinstance(progress, dict) else {}


def flow_run_lease_state(orchestrator_run: OrchestratorAgentRun, *, now: datetime | None = None) -> dict[str, Any]:
    runtime = _runtime_policy(orchestrator_run)
    lease = dict(runtime.get("lease") or {}) if isinstance(runtime.get("lease"), dict) else {}
    lease["is_stale"] = is_flow_run_stale(orchestrator_run, now=now)
    return lease


def is_flow_run_stale(orchestrator_run: OrchestratorAgentRun, *, now: datetime | None = None) -> bool:
    if orchestrator_run.status not in RECOVERABLE_FLOW_STATUSES:
        return False
    runtime = _runtime_policy(orchestrator_run)
    lease = runtime.get("lease")
    if not isinstance(lease, dict):
        return False
    expires_at = _parse_datetime(str(lease.get("lease_expires_at") or ""))
    if expires_at is None:
        return False
    return (now or utc_now()) > expires_at


async def list_stale_v2_flow_runs(
    db: AsyncSession,
    *,
    limit: int = 50,
    now: datetime | None = None,
) -> list[OrchestratorAgentRun]:
    result = await db.execute(
        select(OrchestratorAgentRun)
        .where(
            OrchestratorAgentRun.flow_definition_version_id.is_not(None),
            OrchestratorAgentRun.status.in_(RECOVERABLE_FLOW_STATUSES),
        )
        .order_by(OrchestratorAgentRun.updated_at.asc(), OrchestratorAgentRun.created_at.asc())
        .limit(max(1, min(int(limit or 50), 200)))
    )
    return [run for run in result.scalars().all() if is_flow_run_stale(run, now=now)]


def _runtime_policy(orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = policy.get("runtime")
    return dict(runtime) if isinstance(runtime, dict) else {}


def _lease_seconds_from_policy(policy: dict[str, Any]) -> int:
    runtime = policy.get("runtime")
    value = runtime.get("lease_seconds") if isinstance(runtime, dict) else None
    parsed = _optional_int(value)
    if parsed is None:
        return DEFAULT_FLOW_RUN_LEASE_SECONDS
    return max(MIN_FLOW_RUN_LEASE_SECONDS, min(parsed, MAX_FLOW_RUN_LEASE_SECONDS))


def _optional_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
