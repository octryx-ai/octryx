"""Updating and deactivating Secure Work workflow definitions, with validated mappings."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkItemWorkflowDefinition
from .jira_values import object_value, parse_datetime
from .workflow_access import require_workflow_access

CODE_STATE_UNKNOWN = "workflow_state_unknown"
CODE_STALE = "workflow_stale"
AUDIT_UPDATED = "secure_work.workflow_updated"
AUDIT_ACTIVATION = "secure_work.workflow_activation"
_EDITABLE = ("name", "description", "states", "mappings", "sync_policy", "is_default")


def _key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")[:80]


def _unknown_state(keys: list[str], states: list[dict[str, str]]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": CODE_STATE_UNKNOWN,
            "message": f"Unknown workflow state in mappings: {', '.join(keys)}",
            "states": [state["key"] for state in states],
        },
    )


def _writes_something(mapping: Any) -> bool:
    entry = object_value(mapping)
    return any(entry.get(field) for field in ("source_status", "source_transition", "comment_template", "labels",
                                                 "custom_fields", "sync_back"))


def validate_mapping_keys(raw: Any, states: list[dict[str, str]], *, only_effective: bool = False) -> None:
    known = {state["key"] for state in states}
    unknown = sorted(
        _key(key) for key, entry in object_value(raw).items()
        if _key(key) not in known and (not only_effective or _writes_something(entry))
    )
    if unknown:
        raise _unknown_state(unknown, states)


_STATUS_MAPPING_KEY = "status_state_mapping"


async def validate_intake_status_targets(db: AsyncSession, config: Any) -> None:
    # Checked at create and update only, so an intake stored earlier keeps running.
    from sqlalchemy import select

    from .workflow_mapping import DEFAULT_WORKFLOW_STATES, normalize_workflow_states

    rows = (await db.execute(select(WorkItemWorkflowDefinition).where(
        WorkItemWorkflowDefinition.is_active.is_(True),
        WorkItemWorkflowDefinition.project_id.is_(None) | (WorkItemWorkflowDefinition.project_id == config.project_id),
    ))).scalars().all()
    states = {state["key"]: state for state in DEFAULT_WORKFLOW_STATES}
    for row in rows:
        states.update({state["key"]: state for state in normalize_workflow_states(row.states_json)})
    targets = [
        _key(target)
        for target in object_value(object_value(config.sync_options_json).get(_STATUS_MAPPING_KEY)).values()
        if _key(target)
    ]
    unknown = sorted({target for target in targets if target not in states})
    if unknown:
        raise HTTPException(status_code=422, detail={
            "code": CODE_STATE_UNKNOWN,
            "message": f"Unknown target state in status_state_mapping: {', '.join(unknown)}",
            "states": sorted(states),
        })


def transition_refusal(preview: dict[str, Any], states: list[dict[str, str]]) -> dict[str, Any]:
    to_state = str(preview.get("to_state") or "")
    if to_state and to_state not in {state["key"] for state in states}:
        return {
            "code": CODE_STATE_UNKNOWN,
            "message": f"Unknown workflow state: {to_state}",
            "states": [state["key"] for state in states],
        }
    return {"code": "transition_invalid", "message": str(preview.get("error") or "Invalid transition")}


def _audit(db: AsyncSession, user: User, row: WorkItemWorkflowDefinition, action: str, details: dict) -> None:
    db.add(AuditLog(user_id=user.id, action=action, resource_type="work_item_workflow", resource_id=row.id,
                    project_id=row.project_id,
                    details={"workflow_name": row.name, **details}))


def require_current_version(row: WorkItemWorkflowDefinition, expected: object) -> None:
    # Without ``expected`` there is no check.
    if expected in (None, ""):
        return
    if parse_datetime(expected) != row.updated_at:
        raise HTTPException(status_code=409, detail={
            "code": CODE_STALE,
            "message": "The workflow changed since it was loaded; reload it and apply the change again",
        })


async def update_workflow_definition(
    db: AsyncSession, *, workflow_id: str, current_user: User, payload: dict[str, Any]
) -> dict[str, Any]:
    from .serializers import serialize_workflow_definition
    from .workflow_mapping import (
        _normalize_sync_policy,
        get_workflow_definition,
        normalize_workflow_mappings,
        normalize_workflow_states,
    )

    row = await get_workflow_definition(db, workflow_id)
    await require_workflow_access(db, current_user, row, change=True)
    require_current_version(row, payload.get("updated_at"))
    changed = sorted(key for key in _EDITABLE if key in payload)
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            detail = {"code": "workflow_name_required", "message": "name is required"}
            raise HTTPException(status_code=422, detail=detail)
        row.name = name[:220]
    if "description" in payload:
        row.description = str(payload.get("description") or "").strip() or None
    states = normalize_workflow_states(payload["states"]) if "states" in payload else normalize_workflow_states(
        row.states_json
    )
    if "mappings" in payload:
        validate_mapping_keys(payload.get("mappings"), states)
        raw_mappings = payload.get("mappings")
    else:
        # A state removed by this update may not leave a mapping that still writes something.
        validate_mapping_keys(row.mappings_json, states, only_effective=True)
        raw_mappings = row.mappings_json
    row.states_json = states
    row.mappings_json = normalize_workflow_mappings(raw_mappings, states=states)
    if "sync_policy" in payload:
        row.sync_policy_json = _normalize_sync_policy(payload.get("sync_policy"))
    if "is_default" in payload:
        row.is_default = bool(payload.get("is_default"))
    row.updated_by = current_user.id
    _audit(db, current_user, row, AUDIT_UPDATED, {"changed": changed})
    await db.flush()
    return serialize_workflow_definition(row)


async def set_workflow_active(
    db: AsyncSession, *, workflow_id: str, current_user: User, active: bool, expected_updated_at: object = None
) -> dict[str, Any]:
    from .serializers import serialize_workflow_definition
    from .workflow_mapping import get_workflow_definition

    row = await get_workflow_definition(db, workflow_id)
    await require_workflow_access(db, current_user, row, change=True)
    require_current_version(row, expected_updated_at)
    row.is_active = active
    row.updated_by = current_user.id
    _audit(db, current_user, row, AUDIT_ACTIVATION, {"is_active": active})
    await db.flush()
    return serialize_workflow_definition(row)


__all__ = [
    "CODE_STALE",
    "CODE_STATE_UNKNOWN",
    "require_current_version",
    "set_workflow_active",
    "transition_refusal",
    "update_workflow_definition",
    "validate_intake_status_targets",
    "validate_mapping_keys",
]
