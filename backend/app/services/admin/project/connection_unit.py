"""The connection unit an admin edits: fields, typed secrets, mode switches and completeness.

Shared by the Workspace's own connection (``workspace_connection_service.py``) and the named
connections (``named_connection_service.py``), so both apply the same rules: only the unit's non-secret
fields are ever returned, a typed secret is taken only from the request, a mode switch drops the previous
mode's principal and secret ref, and a connection is complete only with its URL, explicit auth mode
and that mode's credential. Every message names fields and fixed codes only.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.services.atlassian_auth_modes import AtlassianAuthConfigError
from app.services.atlassian_auth_validation import mode_credential_fields, validate_auth_config

from ...secret import secret_ref_field_name
from ...tool_config.connection_fields import (
    auth_mode_fields,
    credential_unit_keys,
    oidc_option_fields,
    principal_fields,
    secret_fields,
    target_fields,
)

CODE_AUTH_INVALID = "atlassian_auth_invalid"


def refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def is_set(value: Any) -> bool:
    return value not in (None, "", [], {})


def editable_fields(tool: str) -> tuple[str, ...]:
    """The non-secret fields of the connection unit: where it connects, how, as whom (and OIDC options)."""
    return (*target_fields(tool), *auth_mode_fields(tool), *principal_fields(tool), *oidc_option_fields(tool))


def connection_keys(tool: str) -> frozenset[str]:
    return credential_unit_keys(tool) | frozenset(target_fields(tool))


def public_fields(tool: str, config: dict[str, Any]) -> dict[str, Any]:
    return {field: config[field] for field in editable_fields(tool) if is_set(config.get(field))}


def secret_status(tool: str, config: dict[str, Any]) -> dict[str, bool]:
    return {field: bool(config.get(field) or config.get(f"{field}_secret_ref")) for field in secret_fields(tool)}


def proposed_unit(tool: str, stored: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """The stored entry with the payload's non-secret connection fields applied (empty removes)."""
    proposed = dict(stored)
    for field in editable_fields(tool):
        if field in payload:
            value = payload[field]
            if value is None or (isinstance(value, str) and not value.strip()):
                proposed.pop(field, None)
            else:
                proposed[field] = value.strip() if isinstance(value, str) else value
    return proposed


def one_credential_unit(tool: str, stored: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    """On a mode switch, drop the principal and secret (ref) fields the new mode does not read."""
    mode_field = auth_mode_fields(tool)[0]
    kept = mode_credential_fields(tool, proposed.get(mode_field))
    if kept is None or proposed.get(mode_field) == stored.get(mode_field):
        return proposed
    unit = (*principal_fields(tool), *secret_fields(tool))
    dropped = {field for field in unit if field not in kept}
    dropped |= {secret_ref_field_name(field) for field in secret_fields(tool) if field not in kept}
    return {key: value for key, value in proposed.items() if key not in dropped}


def kept_secret_view(tool: str, stored: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    """``stored`` without the secrets (refs or plaintext) the proposal does not keep."""
    secrets = {*secret_fields(tool), *(secret_ref_field_name(field) for field in secret_fields(tool))}
    return {key: value for key, value in stored.items() if key not in secrets or key in proposed}


def typed_secrets(tool: str, payload: dict[str, Any]) -> dict[str, str]:
    return {
        field: payload[field].strip()
        for field in secret_fields(tool)
        if isinstance(payload.get(field), str) and payload[field].strip()
    }


def require_complete_unit(tool: str, effective: dict[str, Any]) -> None:
    """An own connection is a full unit: URL, explicit auth mode and that mode's principal/secret."""
    url_field, mode_field = target_fields(tool)[0], auth_mode_fields(tool)[0]
    if not is_set(effective.get(url_field)):
        raise refuse(422, CODE_AUTH_INVALID, f"An own connection needs {url_field}.")
    if not is_set(effective.get(mode_field)):
        raise refuse(422, CODE_AUTH_INVALID, f"An own connection needs {mode_field}.")
    try:
        validate_auth_config(tool, effective)
    except AtlassianAuthConfigError as exc:
        raise refuse(422, exc.code, str(exc)) from None


__all__ = [
    "CODE_AUTH_INVALID",
    "connection_keys",
    "editable_fields",
    "is_set",
    "kept_secret_view",
    "one_credential_unit",
    "proposed_unit",
    "public_fields",
    "refuse",
    "require_complete_unit",
    "secret_status",
    "typed_secrets",
]
