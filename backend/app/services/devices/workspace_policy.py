"""A Workspace's opt-in for device runs: ``agent_gateway_policy.device_runs`` (default off).

Stored like ``seat_mode``: merged into the validated gateway policy through the governed project-config path
with an ``AuditLog`` row. Turning it off stops the Workspace's running device turns.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_gateway.policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY, AgentGatewayPolicyError
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy

from ...models import AuditLog, Project
from ..agent_gateway.policy import load_workspace_policy
from .device_runs_keys import (
    DEFAULTS,
    DEVICE_RUNS_KEY,
    DeviceRunsPolicyError,
    device_runs_section,
    normalize_device_runs,
)

AUDIT_ACTION = "admin.agent_gateway.device_runs_updated"


async def workspace_device_runs(db: AsyncSession, workspace_id: str | None) -> dict[str, Any] | None:
    """The effective section; ``None`` when the Workspace's gateway policy cannot be read (device runs off)."""
    if not workspace_id:
        return None
    loaded = await load_workspace_policy(db, workspace_id)
    return device_runs_section(loaded.policy.raw) if loaded.policy is not None else None


async def workspace_device_limits(db: AsyncSession, workspace_id: str | None) -> dict[str, Any]:
    """``{approval_timeout_s, max_job_minutes, allow_job_edit_scope}`` for jobs of ``workspace_id``."""
    section = await workspace_device_runs(db, workspace_id) or DEFAULTS
    return {key: section[key] for key in ("approval_timeout_s", "max_job_minutes", "allow_job_edit_scope")}


async def set_workspace_device_runs(db: AsyncSession, *, project: Project, patch: Any, actor_id: str) -> dict[str, Any]:
    """Merge ``patch`` into the stored section; raises ``DeviceRunsPolicyError``. Flushes."""
    path = f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.{DEVICE_RUNS_KEY}"
    changes = normalize_device_runs(patch, path)
    config = project.config if isinstance(project.config, dict) else {}
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
    stored = stored if isinstance(stored, dict) else {}
    current = stored.get(DEVICE_RUNS_KEY) if isinstance(stored.get(DEVICE_RUNS_KEY), dict) else {}
    merged = {**current, **changes}
    if "tool_defaults" in changes:
        from .device_runs_keys import merge_tool_defaults

        merged["tool_defaults"] = merge_tool_defaults(current.get("tool_defaults"), changes["tool_defaults"])
    try:
        normalize_agent_gateway_policy({**stored, DEVICE_RUNS_KEY: merged})
    except AgentGatewayPolicyError as error:
        raise DeviceRunsPolicyError("agent_gateway_policy_invalid", error.path) from None
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    was_enabled = device_runs_section(stored).get("enabled") is True
    await apply_project_config_patch(
        db, project=project, patch={AGENT_GATEWAY_POLICY_CONFIG_KEY: {DEVICE_RUNS_KEY: merged}}, actor_user_id=actor_id)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type="workspace", resource_id=project.id,
                    details={"changes": changes}))
    await db.flush()
    effective = {**DEFAULTS, **merged}
    if was_enabled and effective["enabled"] is not True:
        from .jobs import stop_active_jobs

        await stop_active_jobs(db, actor_id=actor_id, reason="workspace_switch_off", workspace_id=project.id)
    return effective


async def workspace_device_setting(db: AsyncSession, workspace_id: str | None, key: str) -> Any:
    """One effective key of the section; the default when the policy cannot be read."""
    section = await workspace_device_runs(db, workspace_id) or DEFAULTS
    return section.get(key, DEFAULTS[key])


__all__ = ["set_workspace_device_runs", "workspace_device_setting", "workspace_device_limits", "workspace_device_runs"]
