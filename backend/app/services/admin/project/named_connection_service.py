"""Admin CRUD and test of named connections, per Workspace or global.

- **List** (``named_connection_view.py``) returns, per connection, its id, name, bound scopes, the unit's
  non-secret fields, which secrets are stored (booleans), its last test and who uses it; never a secret
  value or a ``*_secret_ref``. The connector's own entry is listed as the implicit ``default`` connection.
- **Create/update** validate the name (``default`` is reserved, unique per connector and scope), the
  bound scopes (no key bound by another connection of the same connector and scope: refused, never
  resolved by order) and the complete unit (the connector descriptor's ``complete`` check; for Confluence,
  Jira and ServiceNow URL, explicit auth mode and that mode's credential, the same rules as the Workspace
  connection; ``named_connection_unit.py``). A kept secret never silently follows a
  changed URL or client id (``secret_rebind``, 409). A typed secret is stored in the secret store under
  this connection's own field name (``<field>#<id>``); an empty one keeps the stored one. Secrets a
  mode switch drops are released.
- **Delete** removes the connection and releases its secrets; the audit records who used it.
- **Test** runs the connector's connection test on the connection (typed values for that test only,
  never stored, same rebind rule). A test of the saved values is kept as the connection's
  ``last_test``; it is never recorded as the connector's health, which belongs to the default connection.

Create, update, delete and test are audited with names, scope keys and field names only.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ConnectionWorkspace, ConnectorNamedConnection
from ....time_utils import utc_now
from ...named_connections.contract import (
    CODE_NAME_TAKEN,
    CODE_SCOPE_BOUND_TWICE,
    CODE_TOO_MANY,
    MAX_CONNECTIONS_PER_SCOPE,
    NamedConnectionError,
    bound_elsewhere,
    named_secret_field,
    require_descriptor,
    validate_bound_scopes,
    validate_name,
)
from ...named_connections.descriptor import UnitIncompleteError
from ...named_connections.grants import named_connection_columns
from ...named_connections.store import list_rows, resolved_config, scope_key_of, to_value
from ...secret import secret_ref_field_name, set_secret_value
from ...secret.release import ExcludedHolder, config_secret_refs, release_unreferenced_secrets
from ..connector.connection_test_recording import RunConnectionTest
from .connection_unit import refuse
from .named_connection_steps import (
    CODE_CONNECTION_INVALID,
    _audit,
    _audit_state,
    _flush_named,
    _refuse_unconfirmed_rebind,
    _row,
    _unit,
    _validation_refusal,
)
from .named_connection_view import last_test_record, require_scope, serialize, usage_of_row

AUDIT_CREATED = "admin.named_connection.created"
AUDIT_UPDATED = "admin.named_connection.updated"
AUDIT_DELETED = "admin.named_connection.deleted"
AUDIT_TESTED = "admin.named_connection.tested"
CODE_TEST_UNAVAILABLE = "named_connection_test_unavailable"


async def _check_scope_rules(
    db: AsyncSession, tool: str, project_id: str | None, *, name: str, keys: tuple[str, ...], own_id: str | None
) -> None:
    others = [to_value(row) for row in await list_rows(db, tool, project_id) if row.id != own_id]
    if own_id is None and len(others) >= MAX_CONNECTIONS_PER_SCOPE:
        raise NamedConnectionError(CODE_TOO_MANY, f"At most {MAX_CONNECTIONS_PER_SCOPE} named connections per scope.")
    if any(other.name.lower() == name.lower() for other in others):
        raise NamedConnectionError(CODE_NAME_TAKEN, "Another named connection of this connector has this name.")
    clashes = bound_elsewhere(tool, keys, others)
    if clashes:
        listed = ", ".join(f"{key} ({other})" for key, other in clashes)
        raise NamedConnectionError(CODE_SCOPE_BOUND_TWICE, f"Already bound by another connection: {listed}.")


async def save_named(
    db: AsyncSession,
    *,
    connector: str,
    project_id: str | None,
    payload: dict[str, Any],
    actor_id: str | None,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Create (``connection_id`` None) or update one named connection."""
    tool = await require_scope(db, connector, project_id)
    body = payload if isinstance(payload, dict) else {}
    row = await _row(db, tool, project_id, connection_id) if connection_id is not None else None
    stored = dict(row.config or {}) if row is not None else {}
    try:
        name = validate_name(body["name"] if "name" in body or row is None else row.name)
        raw_keys = body["bound_scopes"] if "bound_scopes" in body or row is None else list(row.bound_scopes or [])
        keys = validate_bound_scopes(tool, raw_keys)
        await _check_scope_rules(db, tool, project_id, name=name, keys=keys, own_id=row.id if row else None)
    except NamedConnectionError as error:
        raise _validation_refusal(error) from None
    proposed, typed = _unit(tool, stored, body)
    if row is not None:
        # Before any secret is stored: a kept secret never silently follows a changed URL or client id.
        await _refuse_unconfirmed_rebind(
            db, tool=tool, project_id=project_id, stored=stored, proposed=proposed, typed=typed,
            payload=body, actor_id=actor_id,
        )
    before = _audit_state(tool, row.name, list(row.bound_scopes or []), stored) if row is not None else None
    if row is None:
        row = await _create_row(db, tool=tool, project_id=project_id, name=name, keys=keys, actor_id=actor_id)
    await _store_typed_secrets(db, tool=tool, project_id=project_id, row_id=row.id, typed=typed, proposed=proposed)
    dropped = config_secret_refs(stored) - config_secret_refs(proposed)
    if typed or proposed != stored:
        row.last_test = None  # a test of the old URL, account or secret says nothing about the new one
    row.name, row.bound_scopes, row.config = name, list(keys), proposed
    row.updated_by, row.updated_at = actor_id, utc_now()
    await _flush_named(db, row)
    if dropped:
        await release_unreferenced_secrets(db, dropped)
    _audit(
        db, actor_id, AUDIT_UPDATED if before is not None else AUDIT_CREATED, row,
        before=before, after=_audit_state(tool, name, list(keys), proposed),
        details={"bound_scopes": list(keys), "replaced_auth_fields": sorted(typed)},
    )
    await db.commit()
    return serialize(row)


async def _create_row(
    db: AsyncSession, *, tool: str, project_id: str | None, name: str, keys: tuple[str, ...], actor_id: str | None
) -> ConnectorNamedConnection:
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name=tool, project_id=project_id, scope_key=scope_key_of(project_id),
        name=name, bound_scopes=list(keys), config={}, created_by=actor_id,
        **named_connection_columns(project_id),
    )
    db.add(row)
    # The row first, so a concurrent save of the same name is refused before any secret is stored.
    await _flush_named(db, row)
    if project_id:  # a Workspace row is available in exactly that Workspace (``selected``)
        db.add(ConnectionWorkspace(connection_id=row.id, workspace_id=project_id))
    return row


async def _store_typed_secrets(
    db: AsyncSession, *, tool: str, project_id: str | None, row_id: str, typed: dict, proposed: dict
) -> None:
    for field, value in typed.items():
        secret = await set_secret_value(
            db, tool_name=tool, field_name=named_secret_field(field, row_id), project_id=project_id, value=value
        )
        proposed.pop(field, None)
        proposed[secret_ref_field_name(field)] = secret.id


async def delete_named(
    db: AsyncSession, *, connector: str, project_id: str | None, connection_id: str, actor_id: str | None
) -> dict[str, Any]:
    tool = await require_scope(db, connector, project_id)
    row = await _row(db, tool, project_id, connection_id)
    config = dict(row.config or {})
    before = _audit_state(tool, row.name, list(row.bound_scopes or []), config)
    # Who used it at deletion (ids, names, keys): the confirm showed it, the audit keeps it.
    used_by = await usage_of_row(db, row)
    released = await release_unreferenced_secrets(
        db, config_secret_refs(config), excluded=ExcludedHolder(table="connector_named_connections", row_id=row.id)
    )
    _audit(db, actor_id, AUDIT_DELETED, row, before=before, after={},
           details={"stored_entries": released.to_payload(), "used_by": used_by})
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "id": connection_id, "stored_entries": released.to_payload(), "used_by": used_by}


async def test_named(
    db: AsyncSession,
    *,
    connector: str,
    project_id: str | None,
    connection_id: str,
    payload: dict[str, Any] | None,
    run_connection_test: RunConnectionTest,
    actor_id: str | None,
) -> dict[str, Any]:
    """Test one named connection; typed values are used for this test only and never stored."""
    tool = await require_scope(db, connector, project_id)
    descriptor = require_descriptor(tool)
    if not descriptor.testable:
        raise refuse(409, CODE_TEST_UNAVAILABLE, f"{descriptor.label} has no connection test.")
    row = await _row(db, tool, project_id, connection_id)
    body = payload if isinstance(payload, dict) else {}
    stored = dict(row.config or {})
    proposed, typed = _unit(tool, stored, body)
    # Before any stored secret is resolved, the same rebind rule as the save.
    await _refuse_unconfirmed_rebind(
        db, tool=tool, project_id=project_id, stored=stored, proposed=proposed, typed=typed,
        payload=body, actor_id=actor_id,
    )
    resolved = await resolved_config(db, replace(to_value(row), config=proposed))
    effective = {**resolved, **typed}
    if descriptor.runtime_guard is not None:
        try:  # a test never falls back to a host or platform credential either
            descriptor.runtime_guard(effective)
        except UnitIncompleteError as incomplete:
            raise refuse(422, CODE_CONNECTION_INVALID, str(incomplete)) from None
    if descriptor.allowlist is not None:
        # Tested as it serves calls: its allowlist is its bound keys (resolver.connection_config), so the test's
        # scope check compares the bound keys with what the account sees.
        effective[descriptor.allowlist.field] = [descriptor.allowlist.entry(key) for key in sorted(row.bound_scopes)]
    result = await run_connection_test(tool, effective)
    unsaved = bool(typed) or proposed != stored
    if not unsaved:
        # Only a test of what is saved says something about the connection; typed values never count.
        row.last_test = last_test_record(result, utc_now())
    _audit(
        db, actor_id, AUDIT_TESTED, row,
        details={"ok": bool(result.get("ok")), "unsaved_values": unsaved},
    )
    await db.commit()
    return result


__all__ = [
    "AUDIT_CREATED",
    "AUDIT_DELETED",
    "AUDIT_TESTED",
    "AUDIT_UPDATED",
    "delete_named",
    "save_named",
    "test_named",
]
