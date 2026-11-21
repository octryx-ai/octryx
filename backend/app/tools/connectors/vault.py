"""Vault connector tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_VAULT

from ..context import ToolContext
from .common import _limit, _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the vault egress rule.
_http_json = connection_http_json(CONNECTION_VAULT)


def _vault_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("vault_url")).rstrip("/")


def _vault_headers(context: ToolContext) -> dict[str, str]:
    token = _string(context.project_config.get("vault_token"))
    headers: dict[str, str] = {}
    if token:
        headers["X-Vault-Token"] = token
    namespace = _string(context.project_config.get("vault_namespace"))
    if namespace:
        headers["X-Vault-Namespace"] = namespace
    return headers


def _vault_mount(context: ToolContext) -> str:
    return _string(context.project_config.get("vault_kv_mount") or "secret").strip("/")


def _vault_allowed_paths(context: ToolContext) -> list[str]:
    return [
        item.strip("/")
        for item in _normalize_string_list(context.project_config.get("vault_allowed_paths"))
        if item.strip("/")
    ]


def _vault_audit_path(context: ToolContext) -> str:
    return _string(context.project_config.get("vault_audit_path") or "sys/audit").strip("/")


def _vault_normalize_path(value: Any) -> str:
    return _string(value).strip().strip("/")


def _vault_path_allowed(context: ToolContext, path: str) -> bool:
    normalized = _vault_normalize_path(path)
    allowed = _vault_allowed_paths(context)
    if not normalized:
        return False
    if not allowed:
        return True
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in allowed)


def _vault_quote_path(path: str) -> str:
    return quote(_vault_normalize_path(path), safe="/")


class ReadVaultSecretTool:
    name = "read_secret"
    description = "Read a secret from HashiCorp Vault, restricted to allowed paths."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        base = _vault_base_url(context)
        path = _vault_normalize_path(params.get("path"))
        if not base:
            return {"error": "No Vault URL configured for this project"}
        if not path:
            return {"error": "path is required"}
        if not _vault_path_allowed(context, path):
            return {"error": "path is not allowed by Vault policy"}
        version = params.get("version")
        data = await _http_json(
            "GET",
            f"{base}/v1/{_vault_mount(context)}/data/{_vault_quote_path(path)}",
            headers=_vault_headers(context),
            params={"version": int(version)} if version not in (None, "") else None,
        )
        payload = data.get("data") or {}
        return {
            "path": path,
            "mount": _vault_mount(context),
            "secret": payload.get("data") or {},
            "metadata": payload.get("metadata") or {},
            "lease_id": data.get("lease_id"),
            "renewable": data.get("renewable"),
        }


class ListVaultSecretsTool:
    name = "list_secrets"
    description = "List child secret keys in HashiCorp Vault for an allowed path."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        base = _vault_base_url(context)
        path = _vault_normalize_path(params.get("path"))
        if not base:
            return {"error": "No Vault URL configured for this project"}
        if not path:
            return {"error": "path is required"}
        if not _vault_path_allowed(context, path):
            return {"error": "path is not allowed by Vault policy"}
        data = await _http_json(
            "LIST",
            f"{base}/v1/{_vault_mount(context)}/metadata/{_vault_quote_path(path)}",
            headers=_vault_headers(context),
        )
        keys = ((data.get("data") or {}).get("keys")) or []
        return {"path": path, "mount": _vault_mount(context), "count": len(keys), "keys": keys}


class RenewVaultLeaseTool:
    name = "renew_lease"
    description = "Renew a HashiCorp Vault lease."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        base = _vault_base_url(context)
        lease_id = _string(params.get("lease_id"))
        if not base:
            return {"error": "No Vault URL configured for this project"}
        if not lease_id:
            return {"error": "lease_id is required"}
        payload: dict[str, Any] = {"lease_id": lease_id}
        increment_seconds = params.get("increment_seconds")
        if increment_seconds not in (None, ""):
            payload["increment"] = int(increment_seconds)
        data = await _http_json(
            "PUT",
            f"{base}/v1/sys/leases/renew",
            headers={**_vault_headers(context), "Content-Type": "application/json"},
            json_body=payload,
        )
        auth = data.get("auth") or {}
        return {
            "lease_id": data.get("lease_id") or lease_id,
            "renewable": data.get("renewable"),
            "lease_duration": data.get("lease_duration"),
            "client_token": auth.get("client_token"),
        }


class RevokeVaultTokenTool:
    name = "revoke_token"
    description = "Revoke a HashiCorp Vault token."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        base = _vault_base_url(context)
        token = _string(params.get("token"))
        if not base:
            return {"error": "No Vault URL configured for this project"}
        if token:
            await _http_json(
                "POST",
                f"{base}/v1/auth/token/revoke",
                headers={**_vault_headers(context), "Content-Type": "application/json"},
                json_body={"token": token},
            )
            return {"status": "revoked", "mode": "token"}
        await _http_json("POST", f"{base}/v1/auth/token/revoke-self", headers=_vault_headers(context))
        return {"status": "revoked", "mode": "self"}


class VaultAuditLogReadTool:
    name = "audit_log_read"
    description = "Read HashiCorp Vault audit information from the configured audit endpoint."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        base = _vault_base_url(context)
        if not base:
            return {"error": "No Vault URL configured for this project"}
        suffix = _vault_normalize_path(params.get("path"))
        audit_path = _vault_audit_path(context)
        full_path = audit_path if not suffix else f"{audit_path}/{suffix}"
        data = await _http_json(
            "GET",
            f"{base}/v1/{_vault_quote_path(full_path)}",
            headers=_vault_headers(context),
            params={"limit": _limit(context, params, default=20, maximum=200)},
        )
        if full_path == "sys/audit":
            return {
                "path": full_path,
                "devices": data.get("data") or data,
                "count": len((data.get("data") or data) or {}),
            }
        entries = ((data.get("data") or {}).get("entries")) or data.get("entries") or []
        return {
            "path": full_path,
            "count": len(entries),
            "entries": entries[: _limit(context, params, default=20, maximum=200)],
        }
