"""Create and update a connection (``POST``/``PUT /api/v1/admin/connections``)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection
from ...models.runtime.named_connection import GLOBAL_SCOPE_KEY
from ...time_utils import utc_now
from ..admin.governance.admin_config_audit_service import record_admin_config_audit
from ..admin.project.connection_unit import refuse
from ..admin.project.named_connection_unit import (
    kept_secret_view,
    one_credential_unit,
    preset_fields_of,
    proposed_unit,
    public_fields,
    require_complete_unit,
    typed_secrets,
)
from ..named_connections.contract import named_secret_field
from ..named_connections.descriptor import ConnectorDescriptor
from ..named_connections.descriptors import descriptor_of
from ..named_connections.origin import CONNECTION_ORIGIN_KEY
from ..secret import secret_ref_field_name, set_secret_value
from ..secret.release import config_secret_refs, release_unreferenced_secrets
from ..tool_config import validate_tool_config
from ..tool_config.secret_rebind import CONFIRM_SECRET_REBIND_FIELD, SecretRebindRequiredError, enforce_secret_rebind
from . import store
from .auth_fields import CODE_LEVEL_REQUIRES_CREDENTIALS, KIND_NONE, chosen_kind, missing_required
from .catalog import auth_kinds, auth_mode_field
from .contract import (
    AVAILABLE_ALL,
    AVAILABLE_IN,
    AVAILABLE_SELECTED,
    CODE_FIELD_INVALID,
    CODE_NAME_INVALID,
    CODE_NAME_TAKEN,
    CODE_PLATFORM_ADMIN_REQUIRED,
    CODE_TYPE_UNKNOWN,
    MAX_NAME_CHARS,
    ORIGIN_CONNECTIONS_API,
    OWNER_PLATFORM,
    OWNER_WORKSPACE,
    STATE_UNTESTED,
    invalid,
    refusal,
)
from .rights import Viewer

AUTH_KEY = "auth"  # ``access.auth``: the sign-in kind of a type without an auth mode field (``token`` | ``none``)
AUDIT_CREATED = "admin.connection.created"
AUDIT_UPDATED = "admin.connection.updated"


def stored_origin(row: ConnectorNamedConnection) -> Any:
    return (row.config or {}).get(CONNECTION_ORIGIN_KEY)


def _name(raw: object) -> str:
    name = raw.strip() if isinstance(raw, str) else ""
    if not name or len(name) > MAX_NAME_CHARS or any(ord(ch) < 32 for ch in name):
        raise invalid("name", f"name: 1-{MAX_NAME_CHARS} characters.", CODE_NAME_INVALID)
    return name


def _descriptor(raw: object) -> ConnectorDescriptor:
    descriptor = descriptor_of(raw) if isinstance(raw, str) else None
    if descriptor is None:
        raise invalid("type", "type must be one of the connection types.", CODE_TYPE_UNKNOWN)
    return descriptor


def _bound_scopes(descriptor: ConnectorDescriptor, raw: object) -> list[str]:
    if not isinstance(raw, list) or len(raw) > 100:
        raise invalid("bound_scopes", "bound_scopes must be a list of at most 100 keys.")
    keys: list[str] = []
    for entry in raw:
        if not descriptor.binding.valid(entry):
            raise invalid("bound_scopes", f"bound_scopes: a key is not a valid {descriptor.binding.label}.")
        key = descriptor.binding.canonical(entry)
        if key not in keys:
            keys.append(key)
    return keys


async def _workspace_list(db: AsyncSession, raw: object) -> list[str]:
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise invalid("workspaces", "workspaces must be a list of Workspace ids.")
    wanted = list(dict.fromkeys(item.strip() for item in raw if item.strip()))
    if len(await store.existing_workspaces(db, wanted)) != len(wanted):
        raise invalid("workspaces", "workspaces: every id must be an existing Workspace.")
    return wanted


def _unit(tool: str, stored: dict, access: dict) -> tuple[dict, dict, object]:
    descriptor = _descriptor(tool)
    kinds, mode_field = auth_kinds(descriptor), auth_mode_field(descriptor)
    explicit = access.get(AUTH_KEY) if mode_field is None else None
    if explicit is not None and explicit not in kinds:
        raise invalid(f"access.{AUTH_KEY}", f"access.{AUTH_KEY} must be one of: {', '.join(kinds)}.")
    proposed = one_credential_unit(tool, stored, proposed_unit(tool, stored, access))
    typed = typed_secrets(tool, access)
    chosen = chosen_kind(descriptor, kinds, mode_field, {**proposed, **typed}, explicit)
    if chosen == KIND_NONE and typed:
        name = sorted(typed)[0]
        raise invalid(f"access.{name}", f"access.{name}: a connection without sign-in takes no secret.")
    if chosen == KIND_NONE:  # public: no credential is kept (a stored one is released below)
        proposed = {key: value for key, value in proposed.items() if not key.endswith("_secret_ref")}
    missing = missing_required(descriptor, kinds, mode_field, {**proposed, **typed}, chosen)
    if missing:
        raise invalid(f"access.{missing[0]}", f"access.{missing[0]} is required for this sign-in kind.")
    if chosen != KIND_NONE:
        require_complete_unit(tool, {**proposed, **typed})
    try:
        validate_tool_config(tool, preset_fields_of(tool, {**proposed, **typed}))
    except ValueError as exc:
        raise refuse(422, CODE_FIELD_INVALID, str(exc)) from None
    return proposed, typed, chosen


def _ownership(viewer: Viewer, body: dict, available_in: str, workspaces: list[str],
               row: ConnectorNamedConnection | None) -> tuple[str, str | None]:
    if not viewer.platform_admin and available_in != AVAILABLE_SELECTED:
        raise refusal(403, CODE_PLATFORM_ADMIN_REQUIRED, "Only platform admins make a connection available everywhere.",
                      "available_in")
    if row is not None:
        kind, owner_ws = str(row.owner_kind), row.owner_workspace_id
    else:
        owner = body.get("owner") if isinstance(body.get("owner"), dict) else {}
        own = not viewer.platform_admin or owner.get("kind") == OWNER_WORKSPACE
        kind = OWNER_WORKSPACE if own else OWNER_PLATFORM
        owner_ws = owner.get("workspace_id") or (workspaces[0] if len(workspaces) == 1 else None)
        if kind == OWNER_PLATFORM:
            owner_ws = None
        elif not owner_ws:
            raise invalid("owner.workspace_id", "owner.workspace_id names the Workspace that owns the connection.")
    if viewer.platform_admin:
        return kind, owner_ws
    if not set(workspaces) <= viewer.admin_workspaces or owner_ws not in viewer.admin_workspaces:
        raise refusal(403, CODE_PLATFORM_ADMIN_REQUIRED, "Workspace admins share connections with their own "
                      "Workspaces only.", "workspaces")
    return kind, owner_ws


async def _name_taken(db: AsyncSession, row_id: str | None, tool: str, scope_key: str, name: str) -> bool:
    stmt = select(ConnectorNamedConnection.id).where(
        ConnectorNamedConnection.tool_name == tool, ConnectorNamedConnection.scope_key == scope_key,
        func.lower(ConnectorNamedConnection.name) == name.lower())
    return any(found != row_id for found in (await db.execute(stmt)).scalars())


def _taken() -> Exception:
    return refusal(409, CODE_NAME_TAKEN, "Another connection of this type has this name.", "name")


async def _flush(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as error:
        if "connector_named_connections" not in str(error.orig) and "uq_connector_named" not in str(error.orig):
            raise
        await db.rollback()
        raise _taken() from None


def audit_state(row: ConnectorNamedConnection, workspaces: list[str]) -> dict[str, Any]:
    tool = str(row.tool_name)
    return {"name": row.name, "available_in": row.available_in, "workspaces": sorted(workspaces),
            "bound_scopes": list(row.bound_scopes or []), "is_active": row.is_active,
            "agent_tools_level": row.agent_tools_level, "fields": sorted(public_fields(tool, dict(row.config or {})))}


def audit(db, actor_id: str, action: str, row: ConnectorNamedConnection, *, before=None, after=None, details=None):
    record_admin_config_audit(db, actor_user_id=actor_id, action=action, resource_type="connection",
                              resource_id=str(row.id), project_id=row.project_id, before=before, after=after,
                              details={"connection_type": row.tool_name, "connection_name": row.name,
                                       **(details or {})})


async def save_connection(db: AsyncSession, viewer: Viewer, body: dict[str, Any],
                          row: ConnectorNamedConnection | None = None) -> ConnectorNamedConnection:
    descriptor = _descriptor(row.tool_name if row is not None else body.get("type"))
    tool = descriptor.connector
    current_ws = sorted((await store.workspaces_of(db, [row.id]))[row.id]) if row is not None else []
    name, available_in, workspaces, owner_kind, owner_ws, keys = await _placement(
        db, viewer, body, row, descriptor, current_ws)
    access = body.get("access") if isinstance(body.get("access"), dict) else {}
    stored = dict(row.config or {}) if row is not None else {}
    proposed, typed, chosen = _unit(tool, stored, access) if (access or row is None) else (dict(stored), {}, None)
    if row is not None:
        await _check_change(db, viewer, body, row, tool=tool, name=name, access=access, stored=stored,
                            proposed=proposed, typed=typed, chosen=chosen)
    before = audit_state(row, current_ws) if row is not None else None
    if row is None:
        if await _name_taken(db, None, tool, GLOBAL_SCOPE_KEY, name):
            raise _taken()
        row = ConnectorNamedConnection(
            id=str(uuid.uuid4()), tool_name=tool, project_id=None, scope_key=GLOBAL_SCOPE_KEY, name=name,
            bound_scopes=[], config={}, created_by=viewer.user_id, owner_kind=owner_kind,
            owner_workspace_id=owner_ws, state=STATE_UNTESTED, is_active=True,
        )
        db.add(row)
        await _flush(db)
    for field, value in typed.items():
        secret = await set_secret_value(db, tool_name=tool, field_name=named_secret_field(field, row.id),
                                        project_id=row.project_id, value=value)
        proposed.pop(field, None)
        proposed[secret_ref_field_name(field)] = secret.id
    # A new connection records where it came from (provenance only; the runtime serves it).
    origin = stored.get(CONNECTION_ORIGIN_KEY) if before is not None else {"kind": ORIGIN_CONNECTIONS_API}
    proposed.pop(CONNECTION_ORIGIN_KEY, None)
    if origin:
        proposed[CONNECTION_ORIGIN_KEY] = origin
    dropped = config_secret_refs(stored) - config_secret_refs(proposed)
    if typed or proposed != stored:
        row.last_test, row.state, row.state_reason, row.last_tested_at = None, STATE_UNTESTED, None, None
    row.name, row.config, row.bound_scopes, row.available_in = name, proposed, keys, available_in
    if "is_active" in body:
        row.is_active = body["is_active"]
    row.updated_by, row.updated_at = viewer.user_id, utc_now()
    await _flush(db)
    await store.set_workspaces(db, row.id, workspaces)
    if dropped:
        await release_unreferenced_secrets(db, dropped)
    audit(db, viewer.user_id, AUDIT_UPDATED if before is not None else AUDIT_CREATED, row, before=before,
          after=audit_state(row, workspaces), details={"replaced_secret_fields": sorted(typed)})
    return row


async def _placement(db: AsyncSession, viewer: Viewer, body: dict[str, Any], row: ConnectorNamedConnection | None,
                     descriptor: ConnectorDescriptor, current_ws: list[str]) -> tuple:
    name = _name(body["name"] if "name" in body or row is None else row.name)
    available_in = body.get("available_in", row.available_in if row is not None else AVAILABLE_SELECTED)
    if available_in not in AVAILABLE_IN:
        raise invalid("available_in", "available_in must be all or selected.")
    workspaces = await _workspace_list(db, body["workspaces"]) if "workspaces" in body else current_ws
    if available_in == AVAILABLE_ALL:
        workspaces = []
    owner_kind, owner_ws = _ownership(viewer, body, available_in, workspaces, row)
    if available_in == AVAILABLE_SELECTED and not workspaces and not owner_ws:
        raise invalid("workspaces", "A connection available in selected Workspaces needs at least one.")
    keys = _bound_scopes(descriptor, body["bound_scopes"]) if "bound_scopes" in body else \
        list(row.bound_scopes or []) if row is not None else []
    if row is not None and not keys and not stored_origin(row):
        # An entry of the per-connector admin (``admin/project/named_connection_service.py`` stores no
        # ``connection_origin``) requires at least one bound key.
        raise invalid("bound_scopes", "This connection serves agent tools today and keeps at least one key.")
    if "is_active" in body and not isinstance(body["is_active"], bool):
        raise invalid("is_active", "is_active must be true or false.")
    return name, available_in, workspaces, owner_kind, owner_ws, keys


async def _check_change(db: AsyncSession, viewer: Viewer, body: dict[str, Any], row: ConnectorNamedConnection, *,
                        tool: str, name: str, access: dict, stored: dict, proposed: dict, typed: dict,
                        chosen: object) -> None:
    level_sent = ((body.get("uses") or {}).get("agent_tools") or {}).get("level") if isinstance(
        body.get("uses"), dict) else None
    if chosen == KIND_NONE and (level_sent or row.agent_tools_level) == "write":
        raise invalid("uses.agent_tools.level", "Agent tools may only read with a connection without sign-in.",
                      CODE_LEVEL_REQUIRES_CREDENTIALS)
    if await _name_taken(db, row.id, tool, row.scope_key, name):
        raise _taken()
    if access or typed:
        try:  # before any secret is stored: a kept secret never silently follows a changed URL or account
            await enforce_secret_rebind(
                db, actor_user_id=viewer.user_id, tool_name=tool, project_id=row.project_id,
                stored=kept_secret_view(tool, stored, proposed), proposed=proposed,
                submitted_secret_fields=set(typed), confirmed=access.get(CONFIRM_SECRET_REBIND_FIELD),
                inherits_global_target=False)
        except SecretRebindRequiredError as refused:
            raise refusal(409, "secret_rebind_required", str(refused.detail().get("message") or
                          "Confirm the stored secret for the new target."), "access") from None


__all__ = ["AUDIT_CREATED", "AUDIT_UPDATED", "audit", "audit_state", "save_connection"]
