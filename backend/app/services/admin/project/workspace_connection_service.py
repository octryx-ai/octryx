"""The Workspace's own Confluence/Jira connection: use the global one, or an own credential unit.

A Workspace either uses the global connection (its entry sets no URL or credential field) or has its
own connection: URL, auth mode, principals and secret refs, as one unit
(``tool_config/connection_fields.py``). This module is the only writer of that unit for the admin
panel; the access save (``admin_project_connector_access_service.py``) never touches it.

- **Read** returns the non-secret fields and which secrets are stored, never a secret or a ref. The
  global part says whether a global entry exists (``configured``) and whether it is enabled
  (``active``); a disabled global entry is never used for a test. ``state`` is computed from the
  stored entry, never from the last test: ``global``, ``own``, ``own_disabled`` (an own entry whose
  connector access is off), or ``own_incomplete`` (an own unit without its URL, auth mode or credential,
  e.g. an own secret left without its URL), with a fixed ``state_summary`` for the last two.
- **Save own** validates the effective unit before any write (the auth-mode rules, a bare
  ``*.atlassian.net`` Confluence URL refused, never rewritten). A kept secret never silently follows a
  changed URL (``secret_rebind``, 409). A typed secret is stored for this Workspace; an empty one keeps
  the stored one. A mode switch drops the previous mode's principal and secret ref, so the entry
  holds one credential unit. ``is_active`` is never changed here.
- **Save global** removes the whole unit, so the Workspace inherits the global connection again.
- **Test** runs the connection test on the effective connection. A typed secret is used for that
  test only and never stored. The same rebind rule as the save applies: a stored secret is
  never sent to a target the test request changes unless it is re-entered or the rebind confirmed
  (409 otherwise). Only a test of the saved connection is recorded as health (never the circuit
  breaker).

Every message names fields and fixed codes only; no value, secret or response body.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.atlassian_auth_modes import AtlassianAuthConfigError

from ....models import Project
from ...connector_health import list_connector_health_rows, serialize_connector_health, upsert_connector_health
from ...secret import resolve_secret_refs, set_secret_value
from ...tool_config import get_tool_config, upsert_tool_config
from ...tool_config.connection_fields import global_config_for_scope, sets_connection_identity
from ...tool_config.secret_rebind import CONFIRM_SECRET_REBIND_FIELD, SecretRebindRequiredError, enforce_secret_rebind
from ..connector.connection_test_recording import RunConnectionTest, run_recorded_connection_test
from ..governance.admin_config_audit_service import record_admin_config_audit
from .connection_unit import connection_keys as _connection_keys
from .connection_unit import kept_secret_view as _kept_secret_view
from .connection_unit import one_credential_unit as _one_credential_unit
from .connection_unit import proposed_unit as _proposed_unit
from .connection_unit import public_fields as _public
from .connection_unit import refuse as _refuse
from .connection_unit import require_complete_unit as _require_complete_unit
from .connection_unit import secret_status as _secret_status
from .connection_unit import typed_secrets as _typed_secrets

CONNECTION_CONNECTORS = frozenset({"confluence", "jira"})
SOURCE_GLOBAL = "global"
SOURCE_WORKSPACE = "workspace"
CODE_SOURCE_INVALID = "connection_source_invalid"
CODE_CONNECTION_INVALID = "connection_invalid"
SAVE_AUDIT_ACTION = "admin.workspace_connection.saved"
STATE_OWN = "own"
STATE_OWN_INCOMPLETE = "own_incomplete"
STATE_OWN_DISABLED = "own_disabled"
DISABLED_SUMMARY = "Own connection disabled for this Workspace: enable the connector in its access settings."
INCOMPLETE_SUMMARY = "Own connection incomplete: set its URL, auth mode and credential, or use the global connection."


_STATE_SUMMARIES = {STATE_OWN_INCOMPLETE: INCOMPLETE_SUMMARY, STATE_OWN_DISABLED: DISABLED_SUMMARY}


def _source(tool: str, config: dict[str, Any]) -> str:
    return SOURCE_WORKSPACE if sets_connection_identity(tool, config) else SOURCE_GLOBAL


def _state(tool: str, config: dict[str, Any], *, active: bool) -> str:
    """``global``, ``own``, ``own_disabled`` or ``own_incomplete``, computed from the stored entry alone.

    A disabled own entry is reported as disabled, whatever its unit holds: no run uses it either way.
    """
    if not sets_connection_identity(tool, config):
        return SOURCE_GLOBAL
    if not active:
        return STATE_OWN_DISABLED
    try:
        _require_complete_unit(tool, config)
    except HTTPException:
        return STATE_OWN_INCOMPLETE
    return STATE_OWN


async def _require(db: AsyncSession, project_id: str, connector: str) -> str:
    tool = str(connector or "").strip().lower()
    if tool not in CONNECTION_CONNECTORS:
        raise HTTPException(status_code=404, detail="Unknown Workspace connection")
    project = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return tool


async def _configs(db: AsyncSession, tool: str, project_id: str) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    entry = await get_tool_config(db, tool, project_id)
    global_entry = await get_tool_config(db, tool, None)
    project_config = dict(entry.config or {}) if entry else {}
    global_config = dict(global_entry.config or {}) if global_entry and global_entry.is_active else {}
    return entry, project_config, global_config


async def get_workspace_connection(db: AsyncSession, *, project_id: str, connector: str) -> dict[str, Any]:
    tool = await _require(db, project_id, connector)
    entry, project_config, _active_global = await _configs(db, tool, project_id)
    global_entry = await get_tool_config(db, tool, None)
    global_config = dict(global_entry.config or {}) if global_entry else {}
    health = (await list_connector_health_rows(db)).get((tool, project_id))
    state = _state(tool, project_config, active=bool(entry and entry.is_active))
    return {
        "connector_name": tool,
        "source": _source(tool, project_config),
        "state": state,
        "state_summary": _STATE_SUMMARIES.get(state),
        "fields": _public(tool, project_config),
        "secret_status": _secret_status(tool, project_config),
        "global": {
            "configured": bool(global_config),
            "active": bool(global_config) and bool(global_entry.is_active),
            "fields": _public(tool, global_config),
            "secret_status": _secret_status(tool, global_config),
        },
        "health": serialize_connector_health(health),
    }


async def _refuse_unconfirmed_rebind(
    db: AsyncSession,
    *,
    tool: str,
    project_id: str,
    stored: dict[str, Any],
    proposed: dict[str, Any],
    typed: dict[str, str],
    payload: dict[str, Any],
    actor_id: str | None,
) -> None:
    """For save and test alike: a kept secret never silently follows a changed target (409)."""
    try:
        await enforce_secret_rebind(
            db,
            actor_user_id=actor_id,
            tool_name=tool,
            project_id=project_id,
            stored=_kept_secret_view(tool, stored, proposed),
            proposed=proposed,
            submitted_secret_fields=set(typed),
            confirmed=payload.get(CONFIRM_SECRET_REBIND_FIELD),
        )
    except SecretRebindRequiredError as refused:
        raise HTTPException(status_code=409, detail=refused.detail()) from None


def _requested_source(payload: dict[str, Any]) -> str:
    source = payload.get("source")
    if source not in (SOURCE_GLOBAL, SOURCE_WORKSPACE):
        raise _refuse(422, CODE_SOURCE_INVALID, "source must be 'global' or 'workspace'.")
    return source


async def save_workspace_connection(
    db: AsyncSession, *, project_id: str, connector: str, payload: dict[str, Any], actor_id: str | None
) -> dict[str, Any]:
    tool = await _require(db, project_id, connector)
    source = _requested_source(payload)
    entry, stored, _global = await _configs(db, tool, project_id)
    if source == SOURCE_GLOBAL:
        proposed = {key: value for key, value in stored.items() if key not in _connection_keys(tool)}
        typed: dict[str, str] = {}
    else:
        proposed = _one_credential_unit(tool, stored, _proposed_unit(tool, stored, payload))
        typed = _typed_secrets(tool, payload)
        _require_complete_unit(tool, {**proposed, **typed})
        # Before any secret is stored: a kept secret never silently follows a changed URL.
        await _refuse_unconfirmed_rebind(
            db, tool=tool, project_id=project_id, stored=stored, proposed=proposed, typed=typed,
            payload=payload, actor_id=actor_id,
        )
        for field, value in typed.items():
            secret = await set_secret_value(db, tool_name=tool, field_name=field, project_id=project_id, value=value)
            proposed.pop(field, None)
            proposed[f"{field}_secret_ref"] = secret.id
    if entry is None and source == SOURCE_GLOBAL:
        return await get_workspace_connection(db, project_id=project_id, connector=tool)
    try:
        await upsert_tool_config(
            db,
            tool_name=tool,
            project_id=project_id,
            config=proposed,
            description=(entry.description if entry else "") or "Workspace connection",
            # Access is the access save's decision; a new entry starts without access.
            is_active=bool(entry.is_active) if entry else False,
        )
    except AtlassianAuthConfigError as exc:
        raise _refuse(422, exc.code, str(exc)) from None
    except ValueError as exc:
        raise _refuse(422, CODE_CONNECTION_INVALID, str(exc)) from None
    record_admin_config_audit(
        db,
        actor_user_id=actor_id,
        action=SAVE_AUDIT_ACTION,
        resource_type="workspace_connection",
        resource_id=f"{project_id}:{tool}",
        before={"source": _source(tool, stored), "fields": sorted(_public(tool, stored))},
        after={"source": source, "fields": sorted(_public(tool, proposed))},
        # Field names only; the key avoids the audit redactor markers ("secret", "credential").
        details={"connector_name": tool, "replaced_auth_fields": sorted(typed)},
    )
    await db.commit()
    return await get_workspace_connection(db, project_id=project_id, connector=tool)


async def _record_incomplete(db: AsyncSession, tool: str, project_id: str) -> None:
    """The saved own connection cannot be used (fail closed): that is this Workspace's health."""
    await upsert_connector_health(
        db, connector_name=tool, project_id=project_id, status="error", response_time_ms=None,
        error=INCOMPLETE_SUMMARY, details=INCOMPLETE_SUMMARY,
    )
    await db.commit()


async def test_workspace_connection(
    db: AsyncSession,
    *,
    project_id: str,
    connector: str,
    payload: dict[str, Any] | None,
    run_connection_test: RunConnectionTest,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Test the effective connection; typed values are used for this test only and never stored."""
    tool = await _require(db, project_id, connector)
    body = payload if isinstance(payload, dict) else {}
    _entry, stored, global_config = await _configs(db, tool, project_id)
    current = _source(tool, stored)
    source = _requested_source(body) if "source" in body else current
    resolved_global = await resolve_secret_refs(db, global_config, tool_name=tool, project_id=None)
    if source == SOURCE_GLOBAL:
        connection_free = {key: value for key, value in stored.items() if key not in _connection_keys(tool)}
        effective = {**resolved_global, **connection_free}
        changed = current != SOURCE_GLOBAL
    else:
        proposed = _one_credential_unit(tool, stored, _proposed_unit(tool, stored, body))
        typed = _typed_secrets(tool, body)
        unchanged = not typed and proposed == stored and current == SOURCE_WORKSPACE
        try:
            # An own connection is tested only as a whole unit (own secret, own target).
            _require_complete_unit(tool, {**proposed, **typed})
        except HTTPException:
            if unchanged:
                await _record_incomplete(db, tool, project_id)
            raise
        # Before any stored secret is resolved, the same rebind rule as the save.
        await _refuse_unconfirmed_rebind(
            db, tool=tool, project_id=project_id, stored=stored, proposed=proposed, typed=typed,
            payload=body, actor_id=actor_id,
        )
        resolved_own = await resolve_secret_refs(db, proposed, tool_name=tool, project_id=project_id)
        effective = {**global_config_for_scope(tool, resolved_global, proposed), **resolved_own, **typed}
        changed = bool(typed) or proposed != stored or current != SOURCE_WORKSPACE
    if changed:
        return await run_connection_test(tool, effective)
    # The saved connection: its outcome is this Workspace's health.
    return await run_recorded_connection_test(
        db, tool_name=tool, project_id=project_id, config=effective, run_connection_test=run_connection_test
    )


__all__ = [
    "CONNECTION_CONNECTORS",
    "SOURCE_GLOBAL",
    "SOURCE_WORKSPACE",
    "get_workspace_connection",
    "save_workspace_connection",
    "test_workspace_connection",
]
