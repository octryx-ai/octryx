"""Device-run policy: the Workspace opt-in and the platform kill switch."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Project, User, UserDevice
from ....services.access_control import get_project_role_for_user
from ....services.admin.governance.admin_access_service import is_global_admin
from ....services.agent_gateway.seat_policy import workspace_seat_decision
from ....services.auth import get_current_user
from ....services.data_classification.workspace_overrides import workspace_level_rules
from ....services.devices.contract import PROFILES
from ....services.devices.device_models import device_model_options
from ....services.devices.device_runs_keys import TOOL_DEFAULT_CHOICES, DeviceRunsPolicyError, tool_defaults
from ....services.devices.platform_switch import device_runs_platform_enabled, set_device_runs_platform_enabled
from ....services.devices.workspace_policy import set_workspace_device_runs, workspace_device_runs
from ....services.model_gateway.data_policy.source import resolve_workspace_data_classification
from ....services.policy_engine.device_translator import device_level_policies, workspace_device_policies

router = APIRouter(tags=["devices"])


def _refusal(reason: str, status: int) -> JSONResponse:
    return JSONResponse({"state": "denied", "reason": reason}, status_code=status)


async def _workspace(db: AsyncSession, user: User, project_id: str) -> tuple[Project | None, bool]:
    role = await get_project_role_for_user(db, user.id, project_id)
    project = await db.get(Project, project_id) if role is not None else None
    return project, role in {"admin", "owner"}


async def _payload(db: AsyncSession, project: Project, can_edit: bool) -> dict[str, Any]:
    section = await workspace_device_runs(db, project.id)
    classification = await resolve_workspace_data_classification(db, project_id=project.id)
    level = classification.classification if classification.resolved else None
    rules = await workspace_level_rules(db, project.config, level) if level else None
    seat = await workspace_seat_decision(db, project.id)
    from ....services.agent_gateway.policy import load_workspace_policy

    raw = (await load_workspace_policy(db, project.id)).policy
    generated = workspace_device_policies(project.id, raw.raw if raw is not None else None)
    if level and rules is not None:
        generated += device_level_policies(level, device_runs_allowed=rules.device_runs_allowed)
    return {
        "project_id": project.id,
        "policy_valid": section is not None,
        **(section or {"enabled": False}),
        "platform_enabled": await device_runs_platform_enabled(db),
        "classification": level,
        "classification_allows": rules.device_runs_allowed if rules is not None else True,
        "seat_allowed": seat.allowed,
        "seat_reason": seat.reason or None,
        "cedar_preview": "\n".join(item.text for item in generated),
        "tool_defaults_effective": tool_defaults(section or {}),
        "can_edit": can_edit,
    }


async def _session_modes(db: AsyncSession, user: User, project_id: str) -> dict[str, Any]:
    from ....services.agent_gateway.role_modes import allowed_modes, session_ceiling  # noqa: PLC0415

    ceiling = await session_ceiling(db, user_id=user.id, workspace_id=project_id)
    return {"session_ceiling": ceiling, "session_modes": allowed_modes(ceiling)}


@router.get("/api/v1/workspaces/{project_id}/agent-gateway/device-runs")
async def get_device_runs(project_id: str, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    project, can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    return {**await _payload(db, project, can_edit), **await _session_modes(db, current_user, project_id)}


@router.put("/api/v1/workspaces/{project_id}/agent-gateway/device-runs")
async def put_device_runs(project_id: str, body: dict[str, Any] = Body(...),
                          current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project, can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    if not can_edit:
        return _refusal("workspace_admin_required", 403)
    try:
        await set_workspace_device_runs(db, project=project, patch=body, actor_id=current_user.id)
    except DeviceRunsPolicyError as error:
        return JSONResponse({"state": "denied", "reason": error.reason, "path": error.path}, status_code=400)
    await db.commit()
    return await _payload(db, project, can_edit)


REMEDY_PREFIX = "device_runs.tool_defaults."


@router.post("/api/v1/workspaces/{project_id}/agent-gateway/device-runs/remedy")
async def apply_device_runs_remedy(project_id: str, body: dict[str, Any] = Body(...),
                                   current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project, can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    if not can_edit:
        return _refusal("workspace_admin_required", 403)
    setting = str(body.get("setting") or "")
    key = setting.removeprefix(REMEDY_PREFIX) if setting.startswith(REMEDY_PREFIX) else ""
    stored = dict(((await workspace_device_runs(db, project.id)) or {}).get("tool_defaults") or {})
    if key == "allowed_tools":
        tool = str(body.get("tool") or "").strip()
        if not tool:
            return _refusal("remedy_tool_missing", 400)
        change: dict[str, Any] = {
            "allowed_tools": [*[item for item in stored.get("allowed_tools") or [] if item != tool], tool]}
    elif key in TOOL_DEFAULT_CHOICES and body.get("value") in TOOL_DEFAULT_CHOICES[key]:
        change = {key: body["value"]}
    else:
        return _refusal("remedy_invalid", 400)
    try:
        await set_workspace_device_runs(db, project=project, patch={"tool_defaults": change},
                                        actor_id=current_user.id)
    except DeviceRunsPolicyError as error:
        return JSONResponse({"state": "denied", "reason": error.reason, "path": error.path}, status_code=400)
    await db.commit()
    return await _payload(db, project, can_edit)


@router.get("/api/v1/workspaces/{project_id}/agent-gateway/device-runs/models")
async def get_device_run_models(project_id: str, profile: str = Query(..., max_length=20),
                                device_id: str = Query("", max_length=40),
                                current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project, _can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    if profile not in PROFILES:
        return _refusal("device_target_invalid", 400)
    device = await db.get(UserDevice, device_id) if device_id else None
    if device_id and (device is None or device.owner_user_id != current_user.id):
        return _refusal("device_target_not_owner", 404)
    options = await device_model_options(db, user_id=current_user.id, workspace_id=project.id, profile=profile,
                                         device_id=device_id)
    return options.payload()


@router.get("/api/v1/admin/device-runs")
async def get_platform_switch(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await is_global_admin(db, current_user.id):
        return _refusal("platform_admin_required", 403)
    return {"enabled": await device_runs_platform_enabled(db)}


@router.put("/api/v1/admin/device-runs")
async def put_platform_switch(body: dict[str, Any] = Body(...), current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    if not await is_global_admin(db, current_user.id):
        return _refusal("platform_admin_required", 403)
    if type(body.get("enabled")) is not bool:
        return _refusal("request_body_invalid", 400)
    await set_device_runs_platform_enabled(db, enabled=body["enabled"], actor_id=current_user.id)
    await db.commit()
    return {"enabled": body["enabled"]}
