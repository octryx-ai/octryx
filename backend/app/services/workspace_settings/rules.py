"""Workspace settings with their first editor: coding-tool rules and budgets."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_gateway.policy_keys import (
    AGENT_GATEWAY_POLICY_CONFIG_KEY,
    BASELINE_DAILY_BUDGET_USD,
    AgentGatewayPolicyError,
    over_baseline,
)
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy

from ...models import Project
from ..agent_gateway.role_modes import role_ceilings
from ..budget.agent_cost_limits import platform_cost_limits
from ..budget.project_cost_limits import (
    INHERIT_COST_LIMIT,
    REQUEST_COST_LIMIT_KEY,
    SESSION_COST_LIMIT_KEY,
    get_project_cost_limit_overrides,
    set_project_cost_limit_overrides,
)
from . import bounds

ERROR_INVALID = "workspace_settings_invalid"


class WorkspaceSettingsError(ValueError):
    def __init__(self, code: str, path: str, reason: str = "") -> None:
        super().__init__(f"{path}: {code}")
        self.code = code
        self.path = path
        self.reason = reason


def _config(project: Project) -> dict[str, Any]:
    return dict(project.config) if isinstance(project.config, Mapping) else {}


def gateway_policy_base(config: Mapping[str, Any]) -> dict[str, Any]:
    return over_baseline(config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY))


async def _write(db: AsyncSession, project: Project, patch: dict[str, Any], actor_id: str) -> None:
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    await apply_project_config_patch(
        db, project=project, patch=patch, actor_user_id=actor_id, replace_keys=frozenset(patch)
    )
    await db.flush()


# --- coding tools & devices ------------------------------------------------------------------------------------------


def coding_view(project: Project) -> dict[str, Any]:
    policy = gateway_policy_base(_config(project))
    permissions = policy.get("client_permissions") if isinstance(policy.get("client_permissions"), Mapping) else {}
    return {
        "requires_governed_routing": policy.get("requires_governed_routing") is True,
        "tool_rules": list(policy.get("tool_rules") or []),
        "client_deny": list(permissions.get("deny") or []),
        "client_ask": list(permissions.get("ask") or []),
        "role_modes": role_ceilings(project),
    }


async def save_coding(
    db: AsyncSession, project: Project, body: Any, *, actor_id: str, platform_admin: bool
) -> dict[str, Any]:
    if not isinstance(body, Mapping) or type(body.get("requires_governed_routing")) is not bool:
        raise WorkspaceSettingsError(ERROR_INVALID, "requires_governed_routing")
    current = gateway_policy_base(_config(project))
    policy = copy.deepcopy(current)
    policy["requires_governed_routing"] = body["requires_governed_routing"]
    policy["tool_rules"] = body.get("tool_rules", [])
    policy["client_permissions"] = {
        "deny": body.get("client_deny", []),
        "ask": list((policy.get("client_permissions") or {}).get("ask") or []),
    }
    if "role_modes" in body:  # what each role's sessions may do in this Workspace
        policy["role_modes"] = body["role_modes"]
    try:
        normalized = normalize_agent_gateway_policy(policy)
    except AgentGatewayPolicyError as error:
        raise WorkspaceSettingsError(ERROR_INVALID, error.path, error.reason) from None
    if not platform_admin:
        bounds.check_coding(current, normalized)
        bounds.check_role_modes(role_ceilings(project), normalized.get("role_modes") or {})
    await _write(db, project, {AGENT_GATEWAY_POLICY_CONFIG_KEY: normalized}, actor_id)
    return coding_view(project)


# --- budget overrides ----------------------------------------------------------------------------------------------


def _amount(value: Any, path: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise WorkspaceSettingsError(ERROR_INVALID, path)
    return float(value)


async def budget_view(db: AsyncSession, project: Project) -> dict[str, Any]:
    overrides = await get_project_cost_limit_overrides(db, project_id=project.id)
    stored = _config(project).get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
    budget = stored.get("session_budget") if isinstance(stored, Mapping) else None
    per_person = budget.get("per_user_daily_usd") if isinstance(budget, Mapping) else None
    if per_person == BASELINE_DAILY_BUDGET_USD:
        per_person = None  # the baseline value is the platform value
    session_cap, request_cap = await platform_cost_limits(db)
    return {
        "platform": {
            "session_usd": float(session_cap.value),
            "request_usd": float(request_cap.value),
            "per_person_daily_usd": float(BASELINE_DAILY_BUDGET_USD),
        },
        "session_usd": float(overrides.session_cost_limit_usd)
        if overrides.session_cost_limit_usd is not None
        else None,
        "request_usd": float(overrides.request_cost_limit_usd)
        if overrides.request_cost_limit_usd is not None
        else None,
        "per_person_daily_usd": float(per_person) if isinstance(per_person, (int, float)) else None,
    }


async def save_budget(
    db: AsyncSession, project: Project, body: Any, *, actor_id: str, platform_admin: bool
) -> dict[str, Any]:
    if not isinstance(body, Mapping):
        raise WorkspaceSettingsError(ERROR_INVALID, "")
    session = _amount(body.get("session_usd"), "session_usd")
    request = _amount(body.get("request_usd"), "request_usd")
    per_person = _amount(body.get("per_person_daily_usd"), "per_person_daily_usd")
    if not platform_admin:
        session_cap, request_cap = await platform_cost_limits(db)
        bounds.check_cap(session, session_cap.value, "session_usd")
        bounds.check_cap(request, request_cap.value, "request_usd")
        bounds.check_daily_budget(per_person)
    await set_project_cost_limit_overrides(
        db,
        project_id=project.id,
        updates={
            SESSION_COST_LIMIT_KEY: INHERIT_COST_LIMIT if session is None else session,
            REQUEST_COST_LIMIT_KEY: INHERIT_COST_LIMIT if request is None else request,
        },
    )
    policy = gateway_policy_base(_config(project))
    # Empty = the platform value, stored explicitly.
    policy["session_budget"] = {"per_user_daily_usd": BASELINE_DAILY_BUDGET_USD if per_person is None else per_person}
    try:
        normalized = normalize_agent_gateway_policy(policy)
    except AgentGatewayPolicyError as error:
        raise WorkspaceSettingsError(ERROR_INVALID, error.path, error.reason) from None
    await _write(db, project, {AGENT_GATEWAY_POLICY_CONFIG_KEY: normalized}, actor_id)
    return await budget_view(db, project)


__all__ = [
    "WorkspaceSettingsError",
    "budget_view",
    "coding_view",
    "gateway_policy_base",
    "save_budget",
    "save_coding",
]
