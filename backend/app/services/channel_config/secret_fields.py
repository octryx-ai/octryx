"""Write-only secret fields of a channel configuration.

A channel's config holds bot credentials (Teams ``app_password``, Slack ``bot_token``, SMTP/IMAP and
Matrix passwords). They never leave the server: :func:`mask_channel_config` drops their values and
reports only ``has_value``; :func:`merge_channel_secrets` keeps the stored value when a save omits a
secret or sends it empty, so editing other fields does not wipe the credential.

A field is secret when its plugin declares ``"secret": True`` or its name is secret-like
(``redaction_policy.is_sensitive_key``) — the name check is a backstop for plugins that forget the flag.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..redaction_policy import is_sensitive_key


def channel_secret_keys(config_fields: Iterable[Mapping[str, Any]], config: Mapping[str, Any]) -> set[str]:
    declared = {
        str(field.get("name"))
        for field in config_fields
        if isinstance(field, Mapping) and field.get("name") and field.get("secret")
    }
    return declared | {str(key) for key in config if is_sensitive_key(str(key))}


def _has_value(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def mask_channel_config(
    config: Mapping[str, Any], config_fields: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, dict[str, bool]]]:
    """Return ``(config without secret values, {secret_key: {"has_value": bool}})``."""
    fields = list(config_fields)
    secret_keys = channel_secret_keys(fields, config)
    masked = {key: value for key, value in config.items() if key not in secret_keys}
    state = {key: {"has_value": _has_value(config.get(key))} for key in sorted(secret_keys)}
    return masked, state


def merge_channel_secrets(
    incoming: Mapping[str, Any],
    stored: Mapping[str, Any],
    config_fields: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Keep each stored secret the incoming config omits or sends empty."""
    merged = dict(incoming)
    for key in channel_secret_keys(list(config_fields), stored):
        if not _has_value(merged.get(key)) and _has_value(stored.get(key)):
            merged[key] = stored[key]
    return merged


__all__ = ["channel_secret_keys", "mask_channel_config", "merge_channel_secrets"]
