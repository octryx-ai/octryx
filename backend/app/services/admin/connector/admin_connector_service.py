"""Admin-panel service helpers for connector management flows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connector_auth.atlassian_modes import AtlassianAuthConfigError
from app.services.connector_auth.atlassian_validation import validate_auth_config

from ...connector_health import (
    list_connector_health_log,
    list_connector_health_rows,
    serialize_connector_health,
)
from ...connector_policy import (
    get_connector_policy,
    list_connector_policies,
    normalize_connector_policy,
    upsert_connector_policy,
)
from ...secret import resolve_secret_refs, set_secret_value
from ...tool_config import TOOL_CONFIG_PRESETS, get_tool_config, list_tool_configs, upsert_tool_config
from ...tool_config.secret_rebind import enforce_global_payload_rebind
from ..governance.admin_config_audit_service import record_admin_config_audit
from .connection_test_recording import run_recorded_connection_test
from .connector_secret_release import connector_secret_candidates, release_connector_secrets


async def list_connectors(
    db: AsyncSession,
    *,
    serialize_connector: Callable[[str, Any, Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    entries = await list_tool_configs(db, None)
    entry_map = {entry.tool_name: entry for entry in entries}
    policy_entries = await list_connector_policies(db, None)
    policy_map = {entry.connector_name: entry for entry in policy_entries}
    health_rows = await list_connector_health_rows(db)
    rows = []
    for tool_name in TOOL_CONFIG_PRESETS:
        payload = serialize_connector(tool_name, entry_map.get(tool_name), policy_map.get(tool_name))
        payload["health"] = serialize_connector_health(health_rows.get((tool_name, "")))
        rows.append(payload)
    return rows


def _apply_public_fields(
    config: dict[str, Any], *, preset: dict[str, Any], secret_fields: list[str], payload: dict[str, Any]
) -> None:
    for field in preset.get("fields", []):
        if field in secret_fields:
            continue
        if field in payload:
            value = payload[field]
            if value is None or value == "":
                config.pop(field, None)
            else:
                config[field] = value


async def _store_submitted_secrets(
    db: AsyncSession, config: dict[str, Any], *, tool_name: str, secret_fields: list[str], payload: dict[str, Any]
) -> None:
    for field in secret_fields:
        raw = str(payload.get(field) or "").strip()
        if raw:
            secret_entry = await set_secret_value(db, tool_name=tool_name, field_name=field, project_id=None, value=raw)
            config.pop(field, None)
            config[f"{field}_secret_ref"] = secret_entry.id


async def _persist_connector_records(
    db: AsyncSession, *, tool_name: str, config: dict[str, Any], payload: dict[str, Any]
) -> None:
    is_active = bool(payload.get("is_active", True))
    try:
        await upsert_tool_config(db, tool_name=tool_name, project_id=None, config=config, is_active=is_active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    policy_payload = normalize_connector_policy(
        payload.get("tool_policy") if isinstance(payload.get("tool_policy"), dict) else {}
    )
    policy_active = bool(payload.get("policy_active", True))
    await upsert_connector_policy(
        db,
        connector_name=tool_name,
        project_id=None,
        policy=policy_payload,
        is_active=policy_active,
    )


async def save_connector(
    db: AsyncSession,
    *,
    tool_name: str,
    payload: dict[str, Any],
    serialize_connector: Callable[[str, Any, Any], dict[str, Any]],
    owner_id: str | None = None,
) -> dict[str, Any]:
    if tool_name not in TOOL_CONFIG_PRESETS:
        raise HTTPException(status_code=404, detail="Unknown connector")
    preset = TOOL_CONFIG_PRESETS[tool_name]
    secret_fields = preset.get("secret_fields", [])
    existing = await get_tool_config(db, tool_name, None)
    existing_policy = await get_connector_policy(db, tool_name, None)
    before_state = _connector_audit_state(existing, existing_policy)
    config: dict[str, Any] = dict(existing.config) if existing and existing.config else {}
    before_config = dict(config)
    _apply_public_fields(config, preset=preset, secret_fields=secret_fields, payload=payload)
    _require_valid_auth_mode(tool_name, config, payload, secret_fields)
    # Before any secret is stored: a kept secret never silently follows a changed target (409).
    await enforce_global_payload_rebind(
        db,
        actor_user_id=owner_id,
        tool_name=tool_name,
        stored=before_config,
        proposed=config,
        payload=payload,
    )
    await _store_submitted_secrets(db, config, tool_name=tool_name, secret_fields=secret_fields, payload=payload)
    await _persist_connector_records(db, tool_name=tool_name, config=config, payload=payload)
    updated = await get_tool_config(db, tool_name, None)
    updated_policy = await get_connector_policy(db, tool_name, None)
    record_admin_config_audit(
        db,
        actor_user_id=owner_id,
        action="admin.connector.saved",
        resource_type="connector_config",
        resource_id=tool_name,
        project_id=None,
        before=before_state,
        after=_connector_audit_state(updated, updated_policy),
        details={"connector_name": tool_name},
    )
    await db.commit()
    return serialize_connector(tool_name, updated, updated_policy)

def _require_valid_auth_mode(
    tool_name: str, config: dict[str, Any], payload: dict[str, Any], secret_fields: list[str]
) -> None:
    submitted = {field: payload[field] for field in secret_fields if str(payload.get(field) or "").strip()}
    try:
        validate_auth_config(tool_name, {**config, **submitted})
    except AtlassianAuthConfigError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from None


async def test_connector(
    db: AsyncSession,
    *,
    tool_name: str,
    run_connection_test: Callable[[str, dict[str, Any]], Any],
) -> dict[str, Any]:
    if tool_name not in TOOL_CONFIG_PRESETS:
        raise HTTPException(status_code=404, detail="Unknown connector")
    existing = await get_tool_config(db, tool_name, None)
    if not existing or not existing.config:
        return {"ok": False, "summary": "Connector not configured yet."}
    resolved = await resolve_secret_refs(db, dict(existing.config), tool_name=tool_name, project_id=None,
                                         purpose="connector.connection_test")
    # A manual test of the saved connection is a health check too, so the card never shows
    # "Unhealthy" beside a successful test.
    return await run_recorded_connection_test(
        db, tool_name=tool_name, project_id=None, config=resolved, run_connection_test=run_connection_test
    )


async def list_connector_health_history(
    db: AsyncSession,
    *,
    tool_name: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if tool_name not in TOOL_CONFIG_PRESETS:
        raise HTTPException(status_code=404, detail="Unknown connector")
    return await list_connector_health_log(db, connector_name=tool_name, limit=limit)


async def delete_connector(
    db: AsyncSession,
    *,
    tool_name: str,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    existing = await get_tool_config(db, tool_name, None)
    existing_policy = await get_connector_policy(db, tool_name, None)
    before_state = _connector_audit_state(existing, existing_policy)
    candidate_secret_ids = await connector_secret_candidates(db, tool_name=tool_name, config_entry=existing)
    if existing:
        await db.delete(existing)
    if existing_policy:
        await db.delete(existing_policy)
    released = await release_connector_secrets(db, candidate_secret_ids, config_entry=existing)
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.connector.deleted",
        resource_type="connector_config",
        resource_id=tool_name,
        project_id=None,
        before=before_state,
        after={},
        # Key without "secret": the audit redactor would blank a key naming it. Ids and names only.
        details={"connector_name": tool_name, "stored_entries": released.to_payload()},
    )
    await db.commit()
    return {"status": "deleted", "stored_entries": released.to_payload()}


def _connector_audit_state(config_entry: Any | None, policy_entry: Any | None) -> dict[str, Any]:
    return {
        "is_active": bool(config_entry.is_active) if config_entry else False,
        "configured": bool(config_entry and config_entry.config),
        "config": dict(config_entry.config or {}) if config_entry else {},
        "policy_active": bool(policy_entry.is_active) if policy_entry else False,
        "tool_policy": dict(policy_entry.policy or {}) if policy_entry else {},
    }
