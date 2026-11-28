"""A channel's credentials live in ``stored_secrets``, owned by the channel and in its Workspace; its config keeps
only ``<field>_secret_ref``. Plugins get the values through the secret access choke point."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import StoredSecret
from ...time_utils import ensure_utc, utc_now_aware
from ..secret import (
    is_secret_ref_field,
    normalize_secret_ref,
    resolve_secret_refs,
    secret_ref_field_name,
    secret_value_field_name,
    set_secret_value,
)
from .secret_fields import channel_secret_keys, has_value

CHANNEL_START = "channel.start"
CHANNEL_SEND = "channel.send"
SECRET_VERSIONS_KEY = "__secret_versions"
UNUSABLE_SECRETS_KEY = "__unusable_secrets"


def channel_secret_scope(channel_id: object) -> str:
    return f"channel:{channel_id}"


def stored_config(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def secret_refs(config: dict[str, Any]) -> dict[str, str]:
    return {secret_value_field_name(key): ref for key, value in config.items()
            if is_secret_ref_field(key) and (ref := normalize_secret_ref(value))}


def _config_fields(plugin_id: str) -> list[dict[str, Any]]:
    from ...plugins import plugin_manager  # noqa: PLC0415 - the plugin registry imports the services

    return list(plugin_manager.get_plugin_info(plugin_id).get("config_fields", []))


async def store_channel_secrets(db: AsyncSession, channel: Any, incoming: dict[str, Any],
                                stored: dict[str, Any]) -> dict[str, Any]:
    kept = secret_refs(stored)
    await _move_to_workspace(db, kept.values(), channel.project_id)
    # A reference is never taken from the request: it could name somebody else's secret.
    config = {key: value for key, value in incoming.items() if not is_secret_ref_field(key)}
    for field in sorted(channel_secret_keys(_config_fields(channel.plugin_id), config) | set(kept)):
        value = config.pop(field, None)
        if has_value(value):
            entry = await set_secret_value(db, tool_name=channel_secret_scope(channel.id), field_name=field,
                                           project_id=channel.project_id, value=str(value))
            config[secret_ref_field_name(field)] = entry.id
        elif field in kept:  # sent empty or left out: the stored secret stays
            config[secret_ref_field_name(field)] = kept[field]
    return config


async def _move_to_workspace(db: AsyncSession, secret_ids, project_id: str | None) -> None:
    ids = sorted(secret_ids)
    if not ids:
        return
    for entry in (await db.execute(select(StoredSecret).where(StoredSecret.id.in_(ids)))).scalars():
        entry.project_id = project_id
    await db.flush()


async def resolved_channel_config(db: AsyncSession, channel: Any, *, purpose: str) -> dict[str, Any]:
    return await resolve_secret_refs(db, stored_config(channel.config), tool_name=channel_secret_scope(channel.id),
                                     project_id=channel.project_id, purpose=purpose)


async def channel_runtime_config(db: AsyncSession, channel: Any, *, purpose: str | None) -> dict[str, Any]:
    # Without a purpose the secrets stay unresolved: enough for the reconciler's fingerprint, which follows each
    # secret's rotation, expiry and revocation instead of its value.
    config = (await resolved_channel_config(db, channel, purpose=purpose) if purpose
              else stored_config(channel.config))
    versions, unusable = await _secret_versions(db, secret_refs(config))
    blocked = sorted(unusable & _required_secret_fields(channel.plugin_id))
    config[SECRET_VERSIONS_KEY] = versions
    config[UNUSABLE_SECRETS_KEY] = blocked
    # A revoked or expired credential the plugin cannot run without keeps the channel unloaded, so the old value
    # stops verifying webhooks and sending messages in every process.
    config["enabled"] = bool(channel.enabled) and not blocked
    config["__channel_id"] = str(channel.id)
    config["__channel_name"] = channel.name
    config["__channel_project_id"] = channel.project_id
    return config


def _required_secret_fields(plugin_id: str) -> set[str]:
    return {str(field["name"]) for field in _config_fields(plugin_id)
            if field.get("name") and field.get("secret") and field.get("required")}


async def _secret_versions(db: AsyncSession, refs: dict[str, str]) -> tuple[dict[str, str], set[str]]:
    # A revocation sets expires_at without touching the rotation stamp, so the stamp carries the expiry and the
    # usability at this moment: an expiry that passes changes the fingerprint as well.
    if not refs:
        return {}, set()
    rows = (await db.execute(select(StoredSecret.id, StoredSecret.last_rotated_at, StoredSecret.updated_at,
                                    StoredSecret.expires_at)
                             .where(StoredSecret.id.in_(sorted(refs.values()))))).all()
    now = utc_now_aware()
    usable: dict[str, bool] = {}
    stamps: dict[str, str] = {}
    for row in rows:
        expires_at = ensure_utc(row.expires_at)
        usable[row.id] = expires_at is None or expires_at > now
        state = "usable" if usable[row.id] else "unusable"
        stamps[row.id] = f"{row.last_rotated_at or row.updated_at}|expires={expires_at}|{state}"
    versions = {field: f"{ref}@{stamps.get(ref, 'missing')}" for field, ref in sorted(refs.items())}
    return versions, {field for field, ref in refs.items() if not usable.get(ref, False)}


__all__ = [
    "CHANNEL_SEND", "CHANNEL_START", "SECRET_VERSIONS_KEY", "UNUSABLE_SECRETS_KEY", "channel_runtime_config",
    "channel_secret_scope", "resolved_channel_config", "secret_refs", "store_channel_secrets", "stored_config",
]
