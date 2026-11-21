"""Data classification settings: the Workspace's level, its effects, the seat switch, the Instance default.

Transport only; decisions live in ``knowledge/projection/workspace_classification_default.py``,
``model_gateway/data_policy/effects.py`` and ``agent_gateway/seat_policy.py``. Every write goes through the
governed project-config path (normalization and admin config audit) plus its own audit row.

- ``GET  /api/v1/workspaces/{project_id}/data-classification`` — any member: ``{effective, source, cleared,
  levels: [{value, rank, effects}], effects, seat_mode, can_edit, instance_default}``. A non-member gets 404.
- ``PUT  /api/v1/workspaces/{project_id}/data-classification`` ``{classification: <level>|null}`` — Workspace
  admin/owner or platform admin; ``null`` clears it and records the cleared marker; an unknown level is
  422 ``data_classification_unknown``.
- ``GET/PUT /api/v1/workspaces/{project_id}/agent-gateway/seat-mode`` ``{seat_mode: forbidden|allowed}`` or
  ``{codex_seat_mode: forbidden|allowed}`` (the Codex seat's own switch), ``{requires_governed_routing: bool}``,
  ``{seat_models: [model id]}``, ``{seat_allows_governed_models: bool}`` or ``{codex_seat_models: [model id]|null}``
  (null: every Codex model) — one key per call, same roles; the answer
  also says whether each seat is in effect given the classification (``codex_in_effect``, ``codex_reason`` for the
  Codex seat) and the stored value of each key (its default when absent).
- ``GET /api/v1/admin/data-classification/default`` — platform admin only; the stored value wins over the env
  bootstrap value. The value changes only through a governed classification version;
  ``POST …/default/apply`` classifies the eligible Workspaces once with the published value.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_gateway.seat_settings import (
    SEAT_SETTING_KEYS,
    invalid_seat_settings,
    seat_mode_set,
    set_workspace_seat_setting,
    stored_seat_mode,
    stored_seat_setting,
)
from app.services.knowledge.projection.workspace_classification_values import (
    DEFAULT_SOURCE_ADMIN,
    ClassificationValueError,
    instance_default_classification,
    instance_default_for,
)

from ...db import get_db
from ...models import Project, User
from ...services.access_control import _user_is_admin, get_project_role_for_user
from ...services.agent_gateway.seat_policy import workspace_seat_decision
from ...services.agent_gateway.seat_policy_keys import (
    BASELINE_SEAT_MODELS,
    CODEX_SEAT_MODE_KEY,
    CODEX_SEAT_MODELS_KEY,
    MAX_MODEL_ID_CHARS,
    MAX_SEAT_MODELS,
    REQUIRES_GOVERNED_KEY,
    SEAT_ALLOWS_GOVERNED_MODELS_KEY,
    SEAT_MODE_KEY,
    SEAT_MODELS_KEY,
    SeatPolicyError,
)
from ...services.auth import get_current_user
from ...services.knowledge.projection.workspace_classification_default import (
    eligible_workspace_ids,
    set_instance_default,
    set_workspace_classification,
    workspace_classification_view,
)
from ...services.model_gateway.data_policy.classification import (
    DATA_POLICY_CLASSIFICATION_CLEARED_FIELD,
    DATA_POLICY_CONFIG_KEY,
)
from ...services.model_gateway.data_policy.effects import classification_effects
from ...services.workspace_settings.bounds import LooseningRefusedError

router = APIRouter(tags=["data-classification"])

NOT_FOUND = "Workspace not found"
WRITE_FORBIDDEN = "Workspace admin or owner role required"
ADMIN_FORBIDDEN = "Platform admin role required"


def _invalid(code: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"errors": [{"code": code}]})


async def _workspace(db: AsyncSession, user: User, project_id: str, *, write: bool) -> tuple[Project, bool]:
    """The Workspace and whether the caller may edit it; a non-member gets the same 404 as a missing one."""
    role = await get_project_role_for_user(db, user.id, project_id)
    project = await db.get(Project, project_id) if role is not None else None
    if project is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    can_edit = role in {"admin", "owner"}
    if write and not can_edit:
        raise HTTPException(status_code=403, detail=WRITE_FORBIDDEN)
    return project, can_edit


def _cleared(project: Project) -> bool:
    section = (project.config or {}).get(DATA_POLICY_CONFIG_KEY) if isinstance(project.config, dict) else None
    return isinstance(section, dict) and bool(section.get(DATA_POLICY_CLASSIFICATION_CLEARED_FIELD))


async def _classification_payload(db: AsyncSession, project: Project, can_edit: bool) -> dict[str, Any]:
    view = await workspace_classification_view(db, project.id)
    levels = await classification_effects(db, workspace_id=project.id)
    current = next((level["effects"] for level in levels if level["value"] == view["effective"]), None)
    return {
        "project_id": project.id,
        "effective": view["effective"],
        "source": view["source"],
        "cleared": _cleared(project),
        "levels": levels,
        "effects": current,
        "seat_mode": stored_seat_mode(project.config),
        "can_edit": can_edit,
        "instance_default": {"classification": view["instance_default"], "state": view["instance_default_state"]},
    }


@router.get("/api/v1/workspaces/{project_id}/data-classification")
async def get_workspace_classification(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=False)
    return await _classification_payload(db, project, can_edit)


@router.put("/api/v1/workspaces/{project_id}/data-classification")
async def put_workspace_classification(
    project_id: str,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=True)
    if "classification" not in body:
        raise _invalid("classification_required")
    try:
        await set_workspace_classification(
            db, project=project, classification=body["classification"], actor_id=current_user.id
        )
    except ClassificationValueError as error:
        raise _invalid(error.code) from None
    await db.commit()
    return await _classification_payload(db, project, can_edit)


async def _seat_payload(db: AsyncSession, project: Project, can_edit: bool, user: User) -> dict[str, Any]:
    decision = await workspace_seat_decision(db, project.id)
    codex = await workspace_seat_decision(db, project.id, codex=True)
    invalid = invalid_seat_settings(project.config)
    return {**_seat_values(project, invalid),
        "project_id": project.id,
        "in_effect": decision.allowed,
        "reason": decision.reason or None,
        "codex_in_effect": codex.allowed,
        "codex_reason": codex.reason or None,
        "seat_models_default": list(BASELINE_SEAT_MODELS),
        "seat_models_limits": {"max_models": MAX_SEAT_MODELS, "max_model_id_chars": MAX_MODEL_ID_CHARS},
        # A stored value that is present but invalid is shown as invalid (``null`` here), never as the default.
        "invalid_settings": invalid,
        "can_edit": can_edit,
        # Only a platform admin may loosen (allow a seat, add a seat model, company models in a seat, switch off
        # governed routing); a Workspace admin or owner may only tighten (``workspace_settings.bounds``).
        "can_loosen": can_edit and await _user_is_admin(db, user.id),
    }


def _seat_values(project: Project, invalid: list[str]) -> dict[str, Any]:
    values = {
        SEAT_MODE_KEY: stored_seat_mode(project.config),
        CODEX_SEAT_MODE_KEY: stored_seat_mode(project.config, CODEX_SEAT_MODE_KEY),
        REQUIRES_GOVERNED_KEY: stored_seat_setting(project.config, REQUIRES_GOVERNED_KEY),
        SEAT_MODELS_KEY: stored_seat_setting(project.config, SEAT_MODELS_KEY),
        SEAT_ALLOWS_GOVERNED_MODELS_KEY: stored_seat_setting(project.config, SEAT_ALLOWS_GOVERNED_MODELS_KEY),
        # ``null`` with the key not in ``invalid_settings``: no list, every Codex model.
        CODEX_SEAT_MODELS_KEY: stored_seat_setting(project.config, CODEX_SEAT_MODELS_KEY),
    }
    shown = {key: (None if key in invalid else value) for key, value in values.items()}
    # Unset and explicitly forbidden differ: an unset switch is open up to internal data.
    return {**shown, "seat_mode_set": seat_mode_set(project.config),
            "codex_seat_mode_set": seat_mode_set(project.config, CODEX_SEAT_MODE_KEY)}


@router.get("/api/v1/workspaces/{project_id}/agent-gateway/seat-mode")
async def get_seat_mode(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=False)
    return await _seat_payload(db, project, can_edit, current_user)


@router.put("/api/v1/workspaces/{project_id}/agent-gateway/seat-mode")
async def put_seat_mode(
    project_id: str,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=True)
    # One seat key per call (``SEAT_SETTING_KEYS``); a body naming none is the Claude seat's ``seat_mode``.
    if any(key not in SEAT_SETTING_KEYS for key in body):
        raise _invalid("unknown_setting")
    named = [key for key in SEAT_SETTING_KEYS if key in body]
    if len(named) > 1:
        raise _invalid("one_setting_per_call")
    key = named[0] if named else SEAT_MODE_KEY
    try:
        await set_workspace_seat_setting(db, project=project, key=key, value=body.get(key), actor_id=current_user.id,
                                         platform_admin=await _user_is_admin(db, current_user.id))
    except SeatPolicyError as error:
        raise _invalid(error.reason) from None
    except LooseningRefusedError as error:
        await db.rollback()
        raise HTTPException(status_code=403, detail={"code": error.code, "path": error.path,
                                                     "reason": error.reason}) from None
    await db.commit()
    return await _seat_payload(db, project, can_edit, current_user)


async def _require_platform_admin(db: AsyncSession, user: User) -> None:
    if not await _user_is_admin(db, user.id):
        raise HTTPException(status_code=403, detail=ADMIN_FORBIDDEN)


async def _default_payload(db: AsyncSession, **extra: Any) -> dict[str, Any]:
    from ...services.model_gateway.data_policy.classification import DATA_CLASSIFICATION_ORDER

    value, state, source = await instance_default_for(db)
    env_value, _env_state = instance_default_classification()
    return {
        "classification": value,
        "state": state,
        "source": source,
        "env_value": env_value,
        "env_in_effect": source != DEFAULT_SOURCE_ADMIN and env_value is not None,
        "levels": list(DATA_CLASSIFICATION_ORDER),
        "unclassified_count": len(await eligible_workspace_ids(db)),
        **extra,
    }


@router.get("/api/v1/admin/data-classification/default")
async def get_instance_default(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _require_platform_admin(db, current_user)
    return await _default_payload(db)


@router.post("/api/v1/admin/data-classification/default/apply")
async def apply_instance_default(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Classify every eligible Workspace with the published default once.

    The default itself changes only through a governed classification version.
    """
    await _require_platform_admin(db, current_user)
    value, _state, _source = await instance_default_for(db)
    if value is None:
        raise _invalid("classification_default_missing")
    result = await set_instance_default(db, classification=value, actor_id=current_user.id, apply_to_unclassified=True)
    await db.commit()
    return await _default_payload(db, applied_count=result["applied_count"])


__all__ = ["router"]
