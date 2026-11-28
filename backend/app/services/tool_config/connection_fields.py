"""Which fields of a connector preset form its connection identity, and how scopes combine them."""

from __future__ import annotations

from functools import cache
from typing import Any

from ..secret import secret_ref_field_name
from .presets import TOOL_CONFIG_PRESETS

_PRINCIPAL_SUFFIXES = ("_username", "_email", "_client_id", "_tenant_id", "_bind_dn", "_role_arn")
_TARGET_SUFFIXES = ("_url", "_host", "_port")
_AUTH_MODE_SUFFIX = "_auth_mode"
_OIDC_MARKER = "_oidc_"
_SELECTOR_SUFFIXES = ("_binary", "_path", "kubeconfig")
_SELECTOR_NAMES = frozenset({"aws_profile", "terraform_var_file", "allow_platform_credentials"})


def _preset(tool_name: str) -> dict[str, Any]:
    return TOOL_CONFIG_PRESETS.get(str(tool_name or "").strip().lower(), {})


def secret_fields(tool_name: str) -> tuple[str, ...]:
    return tuple(_preset(tool_name).get("secret_fields") or ())


def principal_fields(tool_name: str) -> tuple[str, ...]:
    secrets = set(secret_fields(tool_name))
    return tuple(
        field
        for field in _preset(tool_name).get("fields") or ()
        if field not in secrets and field.endswith(_PRINCIPAL_SUFFIXES)
    )


def target_fields(tool_name: str) -> tuple[str, ...]:
    secrets = set(secret_fields(tool_name))
    return tuple(
        field
        for field in _preset(tool_name).get("fields") or ()
        if field not in secrets and field.endswith(_TARGET_SUFFIXES)
    )


def selector_fields(tool_name: str) -> tuple[str, ...]:
    secrets = set(secret_fields(tool_name))
    return tuple(
        field
        for field in _preset(tool_name).get("fields") or ()
        if field not in secrets and (field.endswith(_SELECTOR_SUFFIXES) or field in _SELECTOR_NAMES)
    )


def auth_mode_fields(tool_name: str) -> tuple[str, ...]:
    return tuple(field for field in _preset(tool_name).get("fields") or () if field.endswith(_AUTH_MODE_SUFFIX))


def oidc_option_fields(tool_name: str) -> tuple[str, ...]:
    other = {*secret_fields(tool_name), *principal_fields(tool_name), *target_fields(tool_name)}
    return tuple(
        field for field in _preset(tool_name).get("fields") or () if _OIDC_MARKER in field and field not in other
    )


def client_id_fields(tool_name: str) -> tuple[str, ...]:
    return tuple(
        field for field in principal_fields(tool_name)
        if field.endswith("_oidc_client_id") or field in ("servicenow_client_id", "servicenow_username")
    )


def credential_unit_keys(tool_name: str) -> frozenset[str]:
    secrets = secret_fields(tool_name)
    return frozenset(
        (
            *principal_fields(tool_name),
            *secrets,
            *(secret_ref_field_name(field) for field in secrets),
            *auth_mode_fields(tool_name),
            *oidc_option_fields(tool_name),
        )
    )


def _is_set(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | tuple | dict | set):
        return bool(value)
    return True


def sets_connection_identity(tool_name: str, config: dict | None) -> bool:
    keys = credential_unit_keys(tool_name) | frozenset(target_fields(tool_name))
    return any(_is_set((config or {}).get(key)) for key in keys)


def holds_own_secret(tool_name: str, config: dict | None) -> bool:
    return any(
        _is_set((config or {}).get(field)) or _is_set((config or {}).get(secret_ref_field_name(field)))
        for field in secret_fields(tool_name)
    )


@cache
def _connection_identity_keys() -> frozenset[str]:
    keys: set[str] = set()
    for tool_name in TOOL_CONFIG_PRESETS:
        keys |= credential_unit_keys(tool_name)
        keys |= {*target_fields(tool_name), *selector_fields(tool_name)}
    return frozenset(keys)


def connection_identity_keys() -> frozenset[str]:
    return _connection_identity_keys()


def refused_connection_keys(patch: dict | None) -> list[str]:
    keys = _connection_identity_keys()
    return sorted(key for key, value in (patch or {}).items() if key in keys and value not in (None, ""))


def without_connection_identity(config: dict | None) -> dict:
    """``config`` without any preset's target, selector or credential-unit key, as a new dict."""
    keys = _connection_identity_keys()
    return {key: value for key, value in (config or {}).items() if key not in keys}


def global_config_for_scope(tool_name: str, global_config: dict, project_config: dict | None) -> dict:
    """The part of the global entry a Workspace entry inherits, as a new dict."""
    inherited = dict(global_config or {})
    if sets_connection_identity(tool_name, project_config):
        for key in credential_unit_keys(tool_name):
            inherited.pop(key, None)
    if holds_own_secret(tool_name, project_config):
        for key in target_fields(tool_name):
            inherited.pop(key, None)
    return inherited


__all__ = [
    "auth_mode_fields",
    "client_id_fields",
    "connection_identity_keys",
    "credential_unit_keys",
    "global_config_for_scope",
    "holds_own_secret",
    "oidc_option_fields",
    "principal_fields",
    "refused_connection_keys",
    "secret_fields",
    "selector_fields",
    "sets_connection_identity",
    "target_fields",
    "without_connection_identity",
]
