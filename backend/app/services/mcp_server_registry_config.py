"""Trusted configuration assembly for persisted MCP server registrations."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import McpServerRegistration, McpServerSecretBinding, StoredSecret
from ..models.runtime.mcp_server import MCP_SECRET_TARGET_ENV, MCP_SECRET_TARGET_HEADER
from ..plugins.mcp.models import MCPServerConfig
from .secret import get_secret_value, normalize_secret_ref


def secret_tool_name(server_name: str) -> str:
    return f"mcp:{server_name}"


def runtime_registration_id(mcp_client_manager: Any, server_name: str) -> str | None:
    """Return the registry identity occupying the process-wide runtime name."""
    config = mcp_client_manager.get_server(server_name)
    metadata = getattr(config, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    value = str(metadata.get("registry_id") or "").strip()
    return value or None


async def registration_is_connected(
    registration: McpServerRegistration,
    *,
    mcp_client_manager: Any,
) -> bool:
    """Trust a live runtime slot only when it belongs to this persisted row."""
    if runtime_registration_id(mcp_client_manager, registration.name) != registration.id:
        return False
    return await mcp_client_manager.is_connected(registration.name)


def validate_remote_url(url: Any) -> str:
    normalized = str(url or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Remote MCP URL must use http or https")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Credentialed MCP URLs are not allowed")
    return normalized


def normalize_catalog_values(
    preset: dict[str, Any],
    *,
    settings: dict[str, Any],
    secret_refs: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    fields = {str(field.get("name") or ""): field for field in (preset.get("fields") or [])}
    if set(settings) - set(fields) or set(secret_refs) - set(fields):
        raise HTTPException(status_code=400, detail="Unknown MCP catalog field")

    normalized_settings: dict[str, str] = {}
    normalized_refs: dict[str, str] = {}
    for name, field in fields.items():
        is_secret = str(field.get("type") or "").strip().lower() == "password"
        if is_secret and name in settings:
            raise HTTPException(status_code=400, detail=f"'{name}' must be supplied as a Secret Reference")
        if not is_secret and name in secret_refs:
            raise HTTPException(status_code=400, detail=f"'{name}' is not a secret field")
        if is_secret:
            secret_id = normalize_secret_ref(secret_refs.get(name))
            if secret_id:
                normalized_refs[name] = secret_id
            if field.get("required") and not secret_id:
                raise HTTPException(status_code=400, detail=f"Secret Reference for '{name}' is required")
            continue

        value = str(settings.get(name, field.get("default") or "")).strip()
        options = {str(option) for option in (field.get("options") or [])}
        if options and value not in options:
            raise HTTPException(status_code=400, detail=f"Unsupported value for '{name}'")
        if field.get("required") and not value:
            raise HTTPException(status_code=400, detail=f"'{name}' is required")
        if value:
            normalized_settings[name] = value
    return normalized_settings, normalized_refs


def catalog_transport_metadata(
    preset: dict[str, Any], settings: dict[str, str]
) -> tuple[str, str, list[str], str | None]:
    transport = str(preset.get("transport") or "stdio")
    command = str(preset.get("command") or "")
    args = [str(value) for value in (preset.get("args") or [])]
    url = str(preset.get("url") or "").strip() or None
    return transport, command, args, url


async def validate_secret_bindings(
    db: AsyncSession,
    *,
    server_name: str,
    project_id: str | None,
    preset: dict[str, Any],
    secret_refs: dict[str, str],
) -> list[McpServerSecretBinding]:
    bindings: list[McpServerSecretBinding] = []
    fields = {str(field.get("name") or ""): field for field in (preset.get("fields") or [])}
    for field_name, secret_id in secret_refs.items():
        entry = await db.get(StoredSecret, secret_id)
        if (
            entry is None
            or entry.tool_name != secret_tool_name(server_name)
            or entry.field_name != field_name
            or entry.project_id != project_id
        ):
            raise HTTPException(status_code=400, detail=f"Secret Reference for '{field_name}' is outside MCP scope")
        field = fields[field_name]
        target_kind = MCP_SECRET_TARGET_HEADER if field.get("header") else MCP_SECRET_TARGET_ENV
        target_name = str(field.get("header") or field.get("env_var") or "").strip()
        if not target_name:
            raise HTTPException(status_code=400, detail=f"Secret field '{field_name}' has no trusted target")
        bindings.append(
            McpServerSecretBinding(
                secret_id=secret_id,
                field_name=field_name,
                target_kind=target_kind,
                target_name=target_name,
                target_aliases_json=[str(alias) for alias in (field.get("header_aliases") or [])],
            )
        )
    return bindings


async def resolved_runtime_config(
    db: AsyncSession,
    *,
    registration: McpServerRegistration,
    catalog: dict[str, dict[str, Any]],
) -> MCPServerConfig | None:
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    if registration.catalog_slug:
        preset = catalog.get(registration.catalog_slug)
        if preset is None:
            return None
        fields = {str(field.get("name") or ""): field for field in (preset.get("fields") or [])}
        for field_name, value in dict(registration.settings_json or {}).items():
            field = fields.get(field_name) or {}
            if field.get("env_var"):
                env[str(field["env_var"])] = str(value)
            if field.get("header"):
                headers[str(field["header"])] = str(value)
        for binding in registration.secret_bindings:
            secret = await get_secret_value(
                db,
                secret_id=binding.secret_id,
                expected_tool_name=secret_tool_name(registration.name),
                expected_field_name=binding.field_name,
                expected_project_id=registration.workspace_id,
            )
            if secret is None:
                return None
            target = headers if binding.target_kind == MCP_SECRET_TARGET_HEADER else env
            target[binding.target_name] = secret
            for alias in binding.target_aliases_json or []:
                target[str(alias)] = secret
    return MCPServerConfig(
        name=registration.name,
        command=registration.command,
        args=[str(value) for value in (registration.args_json or [])],
        env=env,
        headers=headers,
        transport=registration.transport,
        url=registration.url,
        auto_start=bool(registration.auto_start),
        description=registration.description,
        metadata={"catalog_slug": registration.catalog_slug, "registry_id": registration.id},
    )


__all__ = [
    "catalog_transport_metadata",
    "normalize_catalog_values",
    "resolved_runtime_config",
    "registration_is_connected",
    "runtime_registration_id",
    "secret_tool_name",
    "validate_remote_url",
    "validate_secret_bindings",
]
