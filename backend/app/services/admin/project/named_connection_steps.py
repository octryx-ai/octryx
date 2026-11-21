"""Shared steps of named-connection saves and tests: lookup, unit validation, rebind check, flush, audit."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ConnectorNamedConnection
from ...named_connections.contract import (
    CODE_NAME_TAKEN,
    CODE_SCOPE_BOUND_TWICE,
    CODE_TOO_MANY,
    NamedConnectionError,
)
from ...named_connections.store import get_row, scope_key_of
from ...tool_config import validate_tool_config
from ...tool_config.secret_rebind import CONFIRM_SECRET_REBIND_FIELD, SecretRebindRequiredError, enforce_secret_rebind
from ..governance.admin_config_audit_service import record_admin_config_audit
from .connection_unit import refuse
from .named_connection_unit import (
    kept_secret_view,
    one_credential_unit,
    preset_fields_of,
    proposed_unit,
    public_fields,
    require_complete_unit,
    typed_secrets,
)

CODE_CONNECTION_INVALID = "connection_invalid"


async def _row(db: AsyncSession, tool: str, project_id: str | None, connection_id: str) -> ConnectorNamedConnection:
    row = await get_row(db, tool, project_id, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Named connection not found")
    return row


def _validation_refusal(error: NamedConnectionError) -> HTTPException:
    status = 409 if error.code in (CODE_NAME_TAKEN, CODE_SCOPE_BOUND_TWICE, CODE_TOO_MANY) else 422
    return refuse(status, error.code, str(error))


async def _refuse_unconfirmed_rebind(
    db: AsyncSession, *, tool: str, project_id: str | None, stored: dict, proposed: dict, typed: dict,
    payload: dict, actor_id: str | None,
) -> None:
    try:
        await enforce_secret_rebind(
            db,
            actor_user_id=actor_id,
            tool_name=tool,
            project_id=project_id,
            stored=kept_secret_view(tool, stored, proposed),
            proposed=proposed,
            submitted_secret_fields=set(typed),
            confirmed=payload.get(CONFIRM_SECRET_REBIND_FIELD),
            inherits_global_target=False,  # a named connection never falls back to the global entry's target
        )
    except SecretRebindRequiredError as refused:
        raise HTTPException(status_code=409, detail=refused.detail()) from None


def _unit(tool: str, stored: dict, payload: dict) -> tuple[dict, dict]:
    proposed = one_credential_unit(tool, stored, proposed_unit(tool, stored, payload))
    typed = typed_secrets(tool, payload)
    require_complete_unit(tool, {**proposed, **typed})
    try:
        # The preset's own fields by the preset's rules; descriptor-only fields (e.g. allowed namespaces) were
        # read by their kind (``named_connection_unit``).
        validate_tool_config(tool, preset_fields_of(tool, {**proposed, **typed}))
    except ValueError as exc:
        raise refuse(422, CODE_CONNECTION_INVALID, str(exc)) from None
    return proposed, typed


_NAME_CONSTRAINTS = ("uq_connector_named_connections_name", "connector_named_connections.")


async def _flush_named(db: AsyncSession, row: ConnectorNamedConnection) -> None:
    """Flush ``row``; a concurrent save that took the name (unique per connector and scope, case-insensitive,
    in the database) is a 409 ``named_connection_name_taken``, any other integrity error is raised as is."""
    try:
        await db.flush()
    except IntegrityError as error:
        if not any(marker in str(error.orig) for marker in _NAME_CONSTRAINTS):
            raise
        await db.rollback()
        raise _validation_refusal(
            NamedConnectionError(CODE_NAME_TAKEN, "Another named connection of this connector has this name.")
        ) from None


def _audit(db, actor_id, action: str, row: ConnectorNamedConnection, *, before=None, after=None, details=None) -> None:
    record_admin_config_audit(
        db,
        actor_user_id=actor_id,
        action=action,
        resource_type="named_connection",
        resource_id=f"{scope_key_of(row.project_id)}:{row.tool_name}:{row.id}",
        before=before,
        after=after,
        # Names, scope keys and field names only; keys avoid the redactor markers ("secret", "credential").
        details={"connector_name": row.tool_name, "connection_name": row.name, **(details or {})},
    )


def _audit_state(tool: str, row_name: str, keys: list[str], config: dict) -> dict[str, Any]:
    return {"name": row_name, "bound_scopes": list(keys), "fields": sorted(public_fields(tool, config))}
