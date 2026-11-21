"""Writes to the MCP server registry: a governed remote server, a catalog install, a configuration update."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import McpServerRegistration
from .mcp_capability_policy import normalized_mcp_server_name
from .mcp_server_registry import (
    _audit_change,
    _normalize_owner,
    _require_workspace,
    get_registration_by_id,
    get_scoped_registration,
)
from .mcp_server_registry_config import (
    catalog_transport_metadata,
    normalize_catalog_values,
    registration_is_connected,
    validate_remote_url,
    validate_secret_bindings,
)

_REMOTE_TRANSPORTS = {"sse", "streamable-http"}


async def create_remote_mcp_server(
    db: AsyncSession,
    *,
    body: dict[str, Any],
    actor_user_id: str | None,
    commit: bool = True,
) -> McpServerRegistration:
    """A governed remote server; ``commit=False`` leaves the commit to a caller that writes more in the same
    transaction (a plugin install) and never rolls back that caller's work."""
    owner_scope, workspace_id = _normalize_owner(body.get("owner_scope"), body.get("workspace_id"))
    if workspace_id:
        await _require_workspace(db, workspace_id)
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    transport = str(body.get("transport") or "streamable-http").strip()
    if transport not in _REMOTE_TRANSPORTS:
        raise HTTPException(status_code=400, detail="Custom MCP servers must use a governed remote transport")
    registration = McpServerRegistration(
        name=name,
        canonical_name=normalized_mcp_server_name(name),
        owner_scope=owner_scope,
        workspace_id=workspace_id,
        transport=transport,
        command="",
        args_json=[],
        url=validate_remote_url(body.get("url")),
        description=str(body.get("description") or ""),
        settings_json={},
        auto_start=bool(body.get("auto_start", False)),
        is_active=bool(body.get("is_active", False)),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    db.add(registration)
    try:
        await db.flush()
    except IntegrityError as exc:
        if commit:
            await db.rollback()
        raise HTTPException(status_code=409, detail=f"MCP server '{name}' already exists") from exc
    await db.refresh(registration, ["secret_bindings"])  # the audit counts them; never a lazy load in async
    await _audit_change(db, registration=registration, actor_user_id=actor_user_id, action="created")
    if commit:
        await db.commit()
    return await get_registration_by_id(db, registration.id)


async def install_catalog_mcp_server(
    db: AsyncSession,
    *,
    slug: str,
    body: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    actor_user_id: str | None,
) -> McpServerRegistration:
    preset = catalog.get(slug)
    if preset is None:
        raise HTTPException(status_code=404, detail="Unknown MCP catalog preset")
    owner_scope, workspace_id = _normalize_owner(body.get("owner_scope"), body.get("workspace_id"))
    if workspace_id:
        await _require_workspace(db, workspace_id)
    name = str(body.get("name") or preset.get("default_name") or slug).strip()
    settings, refs = normalize_catalog_values(
        preset,
        settings=body.get("settings") if isinstance(body.get("settings"), dict) else {},
        secret_refs=body.get("secret_refs") if isinstance(body.get("secret_refs"), dict) else {},
    )
    transport, command, args, url = catalog_transport_metadata(preset, settings)
    registration = McpServerRegistration(
        name=name,
        canonical_name=normalized_mcp_server_name(name),
        owner_scope=owner_scope,
        workspace_id=workspace_id,
        transport=transport,
        command=command,
        args_json=args,
        url=url,
        description=str(body.get("description") or preset.get("description") or ""),
        catalog_slug=slug,
        settings_json=settings,
        auto_start=bool(body.get("auto_start", preset.get("auto_start", False))),
        is_active=bool(body.get("is_active", False)),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    registration.secret_bindings = await validate_secret_bindings(
        db,
        server_name=name,
        project_id=workspace_id,
        preset=preset,
        secret_refs=refs,
    )
    db.add(registration)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"MCP server '{name}' already exists") from exc
    await _audit_change(db, registration=registration, actor_user_id=actor_user_id, action="created")
    await db.commit()
    return await get_registration_by_id(db, registration.id)


async def update_mcp_server(
    db: AsyncSession,
    *,
    name: str,
    workspace_id: str,
    body: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    actor_user_id: str | None,
    mcp_client_manager: Any,
) -> McpServerRegistration:
    registration = await get_scoped_registration(db, name=name, workspace_id=workspace_id)
    previous_active = bool(registration.is_active)
    if registration.catalog_slug:
        preset = catalog.get(registration.catalog_slug)
        if preset is None:
            raise HTTPException(status_code=409, detail="MCP catalog preset is unavailable")
        settings = dict(registration.settings_json or {})
        settings.update(body.get("settings") if isinstance(body.get("settings"), dict) else {})
        existing_refs = {binding.field_name: binding.secret_id for binding in registration.secret_bindings}
        existing_refs.update(body.get("secret_refs") if isinstance(body.get("secret_refs"), dict) else {})
        settings, refs = normalize_catalog_values(preset, settings=settings, secret_refs=existing_refs)
        registration.settings_json = settings
        transport, command, args, url = catalog_transport_metadata(preset, settings)
        registration.transport = transport
        registration.command = command
        registration.args_json = args
        registration.url = url
        registration.secret_bindings = await validate_secret_bindings(
            db,
            server_name=registration.name,
            project_id=registration.workspace_id,
            preset=preset,
            secret_refs=refs,
        )
    elif body.get("settings") or body.get("secret_refs"):
        raise HTTPException(status_code=400, detail="Custom MCP servers do not accept generic credential bindings")
    if "url" in body and body.get("url") is not None:
        if registration.catalog_slug:
            raise HTTPException(status_code=400, detail="Catalog MCP URLs are controlled by the preset")
        registration.url = validate_remote_url(body.get("url"))
    if "description" in body and body.get("description") is not None:
        registration.description = str(body.get("description") or "")
    if "auto_start" in body and body.get("auto_start") is not None:
        registration.auto_start = bool(body["auto_start"])
    if "is_active" in body and body.get("is_active") is not None:
        registration.is_active = bool(body["is_active"])
    registration.updated_by = actor_user_id
    registration.revision += 1
    if await registration_is_connected(registration, mcp_client_manager=mcp_client_manager):
        await mcp_client_manager.disconnect(registration.name)
        mcp_client_manager.unregister_server(registration.name)
    action = "activation_changed" if previous_active != bool(registration.is_active) else "configuration_updated"
    await _audit_change(db, registration=registration, actor_user_id=actor_user_id, action=action)
    await db.commit()
    return await get_registration_by_id(db, registration.id)
