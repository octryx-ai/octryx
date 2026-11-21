"""Read/update operations for admin runtime settings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....runtime_limits import MAX_COMPLETION_TOKENS, MIN_COMPLETION_TOKENS
from ...budget.project_cost_limits import (
    INHERIT_COST_LIMITS_FIELD,
    get_project_cost_limit_overrides,
    project_cost_limit_updates,
    set_project_cost_limit_overrides,
)
from ...context_budget import list_context_budget_profiles
from ...security_analyzer import list_security_analyzer_options
from ...system_config import get_agent_runtime_settings
from ._admin_runtime_payload import build_runtime_settings_payload
from ._admin_runtime_update_core import apply_core_runtime_settings
from ._admin_runtime_update_runtime import apply_execution_and_safety_settings


def _cost_limit_scope_payload(
    *,
    project_id: str | None,
    project_session_limit: Any,
    project_request_limit: Any,
) -> dict[str, Any]:
    normalized_project_id = str(project_id or "").strip()
    has_session_override = project_session_limit is not None
    has_request_override = project_request_limit is not None
    return {
        "scope": "project" if normalized_project_id else "global",
        "project_id": normalized_project_id,
        "session_source": "project" if has_session_override else "global",
        "request_source": "project" if has_request_override else "global",
        "project_session_cost_limit_usd": (
            float(project_session_limit) if has_session_override else None
        ),
        "project_request_cost_limit_usd": (
            float(project_request_limit) if has_request_override else None
        ),
    }


async def _apply_project_cost_limit_scope(
    db: AsyncSession,
    *,
    project_id: str | None,
    runtime_settings: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return runtime_settings, _cost_limit_scope_payload(
            project_id=None,
            project_session_limit=None,
            project_request_limit=None,
        )
    overrides = await get_project_cost_limit_overrides(db, project_id=normalized_project_id)
    scoped_settings = dict(runtime_settings)
    if overrides.session_cost_limit_usd is not None:
        scoped_settings["agent_session_cost_limit_usd"] = float(overrides.session_cost_limit_usd)
    if overrides.request_cost_limit_usd is not None:
        scoped_settings["agent_request_cost_limit_usd"] = float(overrides.request_cost_limit_usd)
    return scoped_settings, _cost_limit_scope_payload(
        project_id=normalized_project_id,
        project_session_limit=overrides.session_cost_limit_usd,
        project_request_limit=overrides.request_cost_limit_usd,
    )


async def get_runtime_settings(
    db: AsyncSession,
    *,
    get_or_create_control_plane_config_func: Callable[..., Any],
    project_id: str | None = None,
) -> dict[str, Any]:
    config = await get_or_create_control_plane_config_func(db)
    runtime_settings = await get_agent_runtime_settings(db)
    runtime_settings, cost_limit_scope = await _apply_project_cost_limit_scope(
        db,
        project_id=project_id,
        runtime_settings=runtime_settings,
    )
    return build_runtime_settings_payload(
        max_output_tokens_default=config.max_output_tokens_default,
        runtime_settings=runtime_settings,
        security_analyzer_options=list_security_analyzer_options(),
        context_budget_profiles=await list_context_budget_profiles(db),
        cost_limit_scope=cost_limit_scope,
    )


async def update_runtime_settings(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    get_or_create_control_plane_config_func: Callable[..., Any],
    project_id: str | None = None,
) -> dict[str, Any]:
    normalized_project_id = str(project_id or "").strip()
    config = await get_or_create_control_plane_config_func(db)
    runtime_settings = await get_agent_runtime_settings(db)
    if normalized_project_id:
        return await _update_project_cost_limits(
            db, config=config, project_id=normalized_project_id, payload=payload
        )
    if payload.get(INHERIT_COST_LIMITS_FIELD):
        # Only a Workspace override can inherit; the platform value is the end of the chain.
        raise HTTPException(
            status_code=400, detail=f"{INHERIT_COST_LIMITS_FIELD} requires a Workspace scope (project_id)"
        )
    _apply_max_output_tokens_default(config, payload)

    await apply_core_runtime_settings(db, payload=payload)
    await apply_execution_and_safety_settings(db, payload=payload, runtime_settings=runtime_settings)

    await db.commit()
    refreshed_runtime_settings = await get_agent_runtime_settings(db)
    return build_runtime_settings_payload(
        max_output_tokens_default=config.max_output_tokens_default,
        runtime_settings=refreshed_runtime_settings,
        security_analyzer_options=list_security_analyzer_options(),
        context_budget_profiles=await list_context_budget_profiles(db),
        cost_limit_scope=_cost_limit_scope_payload(
            project_id=None,
            project_session_limit=None,
            project_request_limit=None,
        ),
    )


async def _update_project_cost_limits(
    db: AsyncSession,
    *,
    config: Any,
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await set_project_cost_limit_overrides(db, project_id=project_id, updates=project_cost_limit_updates(payload))
    await db.commit()
    refreshed_runtime_settings = await get_agent_runtime_settings(db)
    refreshed_runtime_settings, cost_limit_scope = await _apply_project_cost_limit_scope(
        db,
        project_id=project_id,
        runtime_settings=refreshed_runtime_settings,
    )
    return build_runtime_settings_payload(
        max_output_tokens_default=config.max_output_tokens_default,
        runtime_settings=refreshed_runtime_settings,
        security_analyzer_options=list_security_analyzer_options(),
        context_budget_profiles=await list_context_budget_profiles(db),
        cost_limit_scope=cost_limit_scope,
    )


def _apply_max_output_tokens_default(config: Any, payload: dict[str, Any]) -> None:
    if "max_output_tokens_default" not in payload:
        return
    raw_value = payload.get("max_output_tokens_default")
    if raw_value in ("", 0, "0", None):
        config.max_output_tokens_default = None
        return
    value = int(raw_value)
    if not (MIN_COMPLETION_TOKENS <= value <= MAX_COMPLETION_TOKENS):
        raise HTTPException(
            status_code=400,
            detail=f"max_output_tokens_default must be between {MIN_COMPLETION_TOKENS} and {MAX_COMPLETION_TOKENS}",
        )
    config.max_output_tokens_default = value
