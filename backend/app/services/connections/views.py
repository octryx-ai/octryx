"""List and detail views of connections."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection
from ..admin.project.named_connection_unit import public_fields, secret_status
from ..config_effective import Subject, available
from ..named_connections.descriptors import descriptor_of
from ..tool_config.connection_fields import principal_fields
from . import store
from .auth_fields import chosen_kind
from .catalog import auth_kinds, auth_mode_field
from .contract import AVAILABLE_ALL, OWNER_WORKSPACE, STATE_DISABLED
from .errors_and_usage import recent_errors
from .problems_view import problems_by_connection
from .rights import Viewer
from .uses_read import intake_rows, iso, knowledge_rows, uses_of_row, uses_summary


def presented_state(row: ConnectorNamedConnection) -> str:
    return STATE_DISABLED if row.is_active is False else str(row.state or "untested")


def subject_of(row: ConnectorNamedConnection, workspace_ids: frozenset[str]) -> Subject:
    return Subject(available_in=str(row.available_in), workspace_ids=workspace_ids,
                   owner_workspace_id=row.owner_workspace_id)


def access_of(row: ConnectorNamedConnection) -> dict[str, Any]:
    tool, config = str(row.tool_name), dict(row.config or {})
    descriptor = descriptor_of(tool)
    secrets = secret_status(tool, config)
    mode_field = auth_mode_field(descriptor) if descriptor else None
    account = next((config[name] for name in principal_fields(tool) if config.get(name)), None)
    return {
        "base_url": config.get(descriptor.usable_field) if descriptor else None,
        "auth": (config.get(mode_field) if mode_field else
                 chosen_kind(descriptor, auth_kinds(descriptor), None, config) if descriptor else None),
        "account": account,
        "secret_set": any(secrets.values()),
        "fields": public_fields(tool, config),
        "secrets": secrets,
    }


def _owner(row: ConnectorNamedConnection, names: dict[str, str]) -> dict[str, Any]:
    if row.owner_kind == OWNER_WORKSPACE and row.owner_workspace_id:
        workspace_id = row.owner_workspace_id
        return {"kind": OWNER_WORKSPACE,
                "workspace": {"id": workspace_id, "name": names.get(workspace_id, workspace_id)}}
    return {"kind": "platform"}


def _workspaces(row: ConnectorNamedConnection, ids: frozenset[str], names: dict[str, str]) -> list[dict[str, str]]:
    if row.available_in == AVAILABLE_ALL:
        return []
    return [{"id": workspace_id, "name": names.get(workspace_id, workspace_id)}
            for workspace_id in sorted(ids, key=lambda item: names.get(item, item).lower())]


def _problems(found: dict[str, list[dict[str, Any]]], connection_id: str) -> dict[str, Any]:
    return {"problems": found[connection_id], "problems_count": len(found[connection_id])}


async def list_view(db: AsyncSession, viewer: Viewer, *, connection_type: str | None = None,
                    state: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
    rows = await store.list_rows(db, connection_type or None)
    ids = [row.id for row in rows]
    workspaces = await store.workspaces_of(db, ids)
    deviations = await store.deviations_of(db, ids)
    knowledge, intakes = await knowledge_rows(db, ids), await intake_rows(db, ids)
    names = await store.workspace_names(db, [w for ids_ in workspaces.values() for w in ids_]
                                        + [row.owner_workspace_id for row in rows])
    problems = await problems_by_connection(db, viewer, ids)
    listed = []
    for row in rows:
        ws = workspaces[row.id]
        if not viewer.can_see(row, ws):
            continue
        if state and presented_state(row) != state:
            continue
        if workspace_id and not available(subject_of(row, ws), workspace_id):
            continue
        listed.append({
            "id": row.id, "type": row.tool_name, "name": row.name, "state": presented_state(row),
            "state_reason": row.state_reason, "last_tested_at": iso(row.last_tested_at),
            "available_in": row.available_in, "workspaces": _workspaces(row, ws, names),
            "uses": uses_summary(row, knowledge[row.id], intakes[row.id]),
            "owner": _owner(row, names), "can_edit": viewer.can_edit(row, ws),
            "deviation_count": len(deviations[row.id]), "problems_count": len(problems[row.id]),
        })
    return {"connections": listed}


async def detail_view(db: AsyncSession, viewer: Viewer, row: ConnectorNamedConnection) -> dict[str, Any]:
    ws = (await store.workspaces_of(db, [row.id]))[row.id]
    deviations = (await store.deviations_of(db, [row.id]))[row.id]
    knowledge = (await knowledge_rows(db, [row.id]))[row.id]
    intakes = (await intake_rows(db, [row.id]))[row.id]
    names = await store.workspace_names(db, [*ws, row.owner_workspace_id, *(d.workspace_id for d in deviations),
                                             *(k.project_id for k in knowledge), *(i.project_id for i in intakes)])
    return {
        "id": row.id, "type": row.tool_name, "name": row.name, "state": presented_state(row),
        "state_reason": row.state_reason, "last_tested_at": iso(row.last_tested_at), "is_active": row.is_active,
        "access": access_of(row), "bound_scopes": list(row.bound_scopes or []),
        "available_in": row.available_in, "workspaces": _workspaces(row, ws, names),
        "owner": _owner(row, names), "can_edit": viewer.can_edit(row, ws),
        "uses": await uses_of_row(db, row, knowledge, intakes, names),
        "deviations": [
            {"workspace": {"id": item.workspace_id, "name": names.get(item.workspace_id, item.workspace_id)},
             "fields": dict(item.fields or {}), "updated_at": iso(item.updated_at),
             "can_edit": viewer.can_edit_workspace(item.workspace_id)}
            for item in deviations
        ],
        "recent_errors": await recent_errors(db, row, knowledge, intakes),
        **_problems(await problems_by_connection(db, viewer, [row.id]), row.id),
        "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
    }


__all__ = ["access_of", "detail_view", "list_view", "presented_state", "subject_of"]
