"""Write-only secret fields of a channel configuration."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..redaction_policy import is_sensitive_key
from ..secret.service import is_secret_ref_field, secret_value_field_name


def channel_secret_keys(config_fields: Iterable[Mapping[str, Any]], config: Mapping[str, Any]) -> set[str]:
    declared = {
        str(field.get("name"))
        for field in config_fields
        if isinstance(field, Mapping) and field.get("name") and field.get("secret")
    }
    return declared | {str(key) for key in config if is_sensitive_key(str(key))}


def has_value(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def mask_channel_config(
    config: Mapping[str, Any], config_fields: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, dict[str, bool]]]:
    refs = {secret_value_field_name(key) for key, value in config.items() if is_secret_ref_field(key) and value}
    plain = {key: value for key, value in config.items() if not is_secret_ref_field(key)}
    secret_keys = channel_secret_keys(list(config_fields), plain) | refs
    masked = {key: value for key, value in plain.items() if key not in secret_keys}
    return masked, {key: {"has_value": key in refs} for key in sorted(secret_keys)}


__all__ = ["channel_secret_keys", "has_value", "mask_channel_config"]
